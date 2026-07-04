---
ledger_id: 20260606_010000_sprint14_scr_at-rest-encryption
date: 2026-06-06
sprint_id: 14
entry_type: SCR
predecessor: 20260605_203743_sprint13_scr_tier1-finishers
branch: null
merge_commit: dabb712
disposition: COMPLETE (live-verified)
---

# Sprint 14 close — Tier-2 at-rest encryption + audit-stream TPM signing

## Summary

The first Tier-2 sub-project: both SQLite stores (`substrate.db` knowledge store, `sessions.db`
conversation history) encrypted **at rest** under a TPM-sealed DEK dual-wrapped with an offline
recovery key (ADR-025; no new dependency), plus the machinery for a TPM-signed audit stream (#605).
Eight worktree-isolated builder subagents (model sonnet); Orchestrator held the merge gate; builders
never merged to `main` or touched `BUILD_JOURNAL.md`. Full SCR:
`docs/sprints/sprint_14/strategic_completion_report.md`. **Uniquely for this campaign, the LA ran the
batched on-chip ceremony and the production-posture live-verify this sprint — the first piece that is
real on the hardware, not a mock.**

## Deliverables (merges on `main`)

- **EA-1** TPM seal primitive (RSA-2048 OAEP) `fe9cc6f` · **EA-2** field cipher + dual-wrapped DEK
  envelope (AES-256-GCM, HKDF subkeys, AAD, prod-refuses-SoftwareSealer) `18bafe7`.
- **EA-3** substrate.db encryption (text+embedding+filename; boot-cache; keyed-hash dedup; migration) `9807237`.
- **EA-4** sessions.db encryption (content+title; WAL-safe) `1d218c2` (2 rounds).
- **EA-5** audit TPM signer (#605) `274afe3` · **EA-5b** audit refuse-to-start `8fa8384` · **EA-5c** audit-path refuse-to-start `52b3374`.
- **EA-6** ceremony tooling + recovery (`provision_dek_keystore.py`) `6017e5c` (2 rounds).
- **EA-7** store fail-closed (prod refuses on missing keystore) `6e6a0c6` · **EA-8/EA-9** test-isolation.
- ADR-025 ACCEPTED `804a0ef`; roadmap §8 (live-memory #611) + §9 (capstone #612) + Cleaner deferral (#613); ceremony runbook `e9c7c26`; trust anchor recorded (ADR-025 §5).

## Highlights (portfolio)

- **Two merge-gate catches:** EA-4 round-1 "built but wired into nothing" (encryption not connected to
  the launcher — the Sprint-13 trap recurring); EA-6 round-1 recovery path correct only by-accident
  (relied on a dev stub raising a caught exception). Both caught by diff-review against the criterion,
  fixed with teeth.
- **Live-verify caught a real at-rest gap:** the functional smoke test passed, but the raw-byte check
  found the pre-existing dev data still plaintext; wiped → re-verified 0-plaintext.
- **A worktree-cwd quirk recurred and was recovered non-destructively** (preserve-then-cherry-pick);
  the branch-guard added afterward caught the next recurrence and blocked a wrong-branch merge.
- **A test-isolation defect (+ the operator-data incident it caused)** — the suite wrote into the real
  `%LOCALAPPDATA%`, damaging the live `sessions.db`; harmless ONLY because no real data existed yet.
  Fixed (EA-8 per-package + EA-9 root conftest); recovery preserved the damaged file. The cleanest
  validation yet of "born-encrypted before first real use is well-timed, not urgent."

## Live verification (production posture) — PERFORMED + PASS

Ceremony run on the real TPM (3 keys: `BlarAI-DEKSeal` RSA seal, `BlarAI-Audit-Signing-Key-v1` audit,
offline recovery key); `BLARAI_DEK_KEYSTORE` set; production boot confirmed the encrypted stores live;
an independent raw-column scan found **0 plaintext** across all sensitive columns; recovery key stored
off-box. The #598 criterion "at-rest encryption on, with a tested recovery path" is **MET in
production posture**. Audit TPM-signing + JWT live activation remain gated on the later dev-mode-off
flip (Tier-2 VM/mTLS) — honestly named, not claimed.

## Quality gate

`pytest shared/ services/ launcher/ -m "not hardware and not winui and not slow"` = **2056 passed, 0
failed, 15 deselected** on integrated `main` (kickoff baseline 1883 → 2056, zero regressions). SDV
criteria **7/7 MET**. SWAGR: **PASS (CONCERNS) — 0 CRITICAL, 0 MAJOR, 4 MINOR**, all dispositioned
(MINOR-1 trust anchor recorded; MINOR-2 this ledger entry; MINOR-3 EA-7; MINOR-4 EA-8+EA-9).

## Campaign-pacing note (toward #598)

Deferring the Cleaner (UC-003, #613) off the gate shortens the critical path — it was the largest
single Tier-2 build. Remaining gate-critical Tier-2 = **run-in-VM + mTLS + per-boot certs**, which also
carries the **dev-mode-off flip** that activates the audit-TPM-signing + JWT keys already provisioned.
Tier-3 items (dependency pinning #560, full weight-integrity FUT-04, the runtime egress guard) are
light and disjoint — candidates for a parallel wave. The capstone security presentation (#612) is the
closing bookend at/after #598. The merge-gate + the on-chip ceremonies are the deliberate
serialization points; otherwise the path to #598 is visibly shortening.

## Carry-overs

Audit-TPM-signing + JWT live + dev-mode-off flip (Tier-2 VM/mTLS + LA live-verify); audit retention
#607 + tail-deletion attestation #606; live-memory attacker #611 (deferred-not-denied, roadmap §8);
the Cleaner #613 (post-#598 fast-follow); capstone presentation #612; embedded-PAN PII #608. The
air-gap stays up; #598 remains the GO/NO-GO.
