---
ledger_id: 20260607_094439_sprint15_scr_production-posture-flip
date: 2026-06-07
sprint_id: 15
entry_type: SCR
predecessor: 20260606_010000_sprint14_scr_at-rest-encryption
branch: null
merge_commit: null
disposition: COMPLETE (8/8 MET, Auditor-confirmed; activation live-verified)
---

# Sprint 15 close — Tier-2 production posture: per-boot mTLS + dev-mode-off flip (fidelity-2)

## Summary

The sprint that made "BlarAI works" mean "it works in the posture that ships." It flipped the running
default from dev-mode to production (`dev_mode=false`) and brought three dormant security mechanisms
alive at once: per-boot ephemeral mTLS over the vsock channel, audit-stream TPM signing, and JWT signing
(the latter two provisioned-but-dormant since Sprint 14). The dev-mode-as-default trap is closed —
production is the HOST default behind a regression lock, with the explicit `dev_mode=true` opt-in
preserved as the loud, air-gapped escape hatch. Per-tier DEC-15 fleet wave of worktree-isolated builder
subagents (model sonnet); the Orchestrator held the merge gate; builders never merged to `main` or
touched `BUILD_JOURNAL.md`. Full SCR: `docs/sprints/sprint_15/strategic_completion_report.md`.
Fidelity-2: the host-local cert machinery + `dev_mode=false` are proven; the guest↔host AF_HYPERV
boundary is deferred (#615).

## Deliverables (merges on `main`)

- **EA-1** per-boot mTLS cert gen + ADR-026 `336fcc2` · **EA-2** dev-mode-off flip MECHANISM + locks
  `bab1219` · **EA-3** cascade + off-chip stub harness (7/7) + substrate ratify `b499bc6`.
- **EA-4a** ceremony helpers `217ba32` · **EA-4b** ACTIVATION flip (HOST default → production) + 6 locks
  `e1858a5` · **EA-4c** vsock HV_PROTOCOL_RAW proto fix `c26cf11` · **EA-4d** fidelity-2 host transport
  `04c45fd` · **EA-4e** orch + router cert mint `a410be9` · **EA-4f** PA HANDSHAKE_REQUEST handler `5ac5f9e`.
- **#618** decrypt-quarantine — session store `4af2033` + substrate sibling `6fe1fcc` (live-verify-surfaced;
  ADR-025 §2.7 posture amendment).
- **#620** gateway→AO prompt routing `ecbd991` (single-source-of-truth `resolve_gateway_port` + real
  gateway↔AO round-trip integration test + model-loaded prompt-flow preflight default-ON in production).
- Journal fold (13 fragments → lessons 57–66) `1730a39`; independent SWAGR `423167e`.

## Highlights (portfolio)

- **The live-verify was the defining work — it caught ten production-only defects the green suite could
  not.** The unit suite was green throughout (2126 at EA-4f), yet the first real `dev_mode=false` boots
  surfaced 7 boot-cascade gaps + 2 decrypt-bricks + 1 prompt misroute, each in a seam the units mock.
  "Mocks pass, seams break" (BUILD_JOURNAL lesson 56; the `TEST_GOVERNANCE §2.7` mandate is the systemic
  answer).
- **A downstream fix masked an upstream defect.** EA-4f taught the PA to answer the gateway handshake,
  which made the boot *look* healthy and hid #620 (gateway wired to PA:5000, not AO:5001) until a real
  prompt was sent. Fix: single-source-of-truth `resolve_gateway_port` + a real gateway↔AO round-trip test
  (red→green). Lesson 65.
- **A test that locked a *defect*, corrected — not just a feature locked.** The #618 decrypt-brick was
  guarded by a *green* Sprint-14 test asserting the brick; the fix rewrote that test to the corrected
  quarantine posture while keeping the single-record hard-fail. Lesson 66. A class-audit caught the
  substrate sibling before it surfaced in production (lesson 64).
- **Honest failure (caught before the permanent record):** the outgoing session twice claimed "no
  automated UI tests" — wrong; a pywinauto harness exists (#563). #621 was corrected from "build FlaUI"
  to "extend the existing pywinauto harness." Verify your own claims on disk, even the confident ones.

## Live verification (production posture) — activation PERFORMED + PASS

The LA ran the EA-4 ceremony (JWT signing key net-new via `provision_signing_key`; DEK + audit keys
confirmed present from the Sprint-14 ceremony) and the production live-verify on the real hardware.
Boot-1 PASSED (LA-confirmed 2026-06-06): the dev→prod flip live, the per-boot mTLS handshake on the
freshly-minted CA with no dev fallback; the new default-ON model-loaded prompt-flow preflight passed
before the UI; prompts respond; vision describes a never-seen photo; Qwen3-VL evicts (+3857 MB). The
22:36 `launcher.log` is the on-disk evidence; the Auditor read it line-by-line. The cold-reboot
continuity repeat is a low-risk routine confirmation (TPM keys + DEK keystore + deterministic quarantine
persist across an OS restart), capturable anytime.

## Quality gate

`pytest shared/ services/ launcher/ -m "not hardware and not winui and not slow"` = **2172 passed, 2
skipped, 15 deselected** on integrated `main` (kickoff 2055 → 2172; zero regressions), re-run live at the
close and **independently reproduced by the Auditor**. SDV criteria **8/8 MET**. Independent SWAGR:
**STRONG_ALIGNMENT — 0 CRITICAL, 0 MAJOR, 6 MINOR**, all dispositioned at close (MINOR-1 ADR-026
cert-count 5→9 fixed; MINOR-2 this ledger entry; MINOR-3 #618/#620 closed; MINOR-4 CLAUDE.md Active-State
refreshed; MINOR-5 TEST_GOVERNANCE §1 annotated; MINOR-6 SECURITY_ROADMAP reconciliation tracked #613).
The Auditor graded criterion #8 a clean MET — *stronger* than the SCR's cautious self-grade (seven
zero-manual production-default boots already ran 2026-06-06).

## Campaign-pacing note (toward #598)

Sprint 15 paid the central posture debt (dev-mode-as-default) and *named* the testing debt: the unit
suite + the #563 scenario harness systematically miss production seams, and the §2.7 "test the seam"
mandate has near-zero CI enforcement yet. The single most valuable Sprint-16 move is **#619** (the
production-parity test lane) so the mock-passes-prod-crashes class hits CI, not the LA's terminal.
Remaining #598 gate-critical: #615 (guest boundary), #106 (full FUT-04 weight integrity), Tier-3 egress
mediation, #612 (capstone). The air-gap stays up; **#598 remains the GO/NO-GO**.

## Carry-overs

#619 (production-parity test lane — top priority), #621 (extend the pywinauto GUI harness + a
model-loaded tier — NOT a from-scratch FlaUI build), #622 (comprehensive automated-test-coverage
initiative), #623 (gateway handshake method rename), the cold-reboot continuity boot (routine
confirmation); #615 (guest-boundary handshake), #106 (full FUT-04 weight integrity), #612 (capstone);
MINOR-6 SECURITY_ROADMAP Cleaner-reference reconciliation tracked #613. The air-gap stays up; #598 remains
the GO/NO-GO.

## Continuity addendum (2026-06-07)

The cold-reboot continuity boot (criterion #8) — named at close as the one routine confirmation
outstanding — was **CAPTURED + PASS** the same day. After an OS reboot, the LA's first `python -m launcher`
(2026-06-07 09:58, the first 2026-06-07 log line) booted zero-manual into production posture (`dev_mode
interlock: PASSED`), minted fresh per-boot mTLS certs, passed the real-runtime handshake + the default-ON
prompt-flow preflight, auto-quarantined the 2 dev-era rows (app kept serving), served the LA's prompt
(`send_prompt → generation complete`), and shut down clean (rc=0). The TPM-sealed keys + DEK keystore +
deterministic quarantine all survived the OS restart. (The VM logged "already running" — it auto-started
with the host, the normal daily-driver state.) Criterion #8 is fully captured; disposition unchanged:
**COMPLETE — 8/8 MET, live-verified (activation + cold-reboot continuity).**
