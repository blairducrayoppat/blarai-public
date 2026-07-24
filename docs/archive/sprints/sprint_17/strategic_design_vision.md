---
sprint_id: 17
sprint_name: "The Boot Cluster"
sdv_version: 1
status: "READY FOR EXECUTION — all scope decisions pre-made (ADR-027 egress, ADR-028 attestation). Scope checkpoint = the execution session's comprehension gate (guide-reviewed + LA-confirmed); no separate sign-off ceremony, per the LA's minimal-involvement directive 2026-06-07."
tracking_task: 628
authored_by: "LA-guide session (Sprint-16 reviewer / Sprint-17 planner)"
authored_on: "2026-06-07"
predecessor_sprint: 16
gate: "#598 air-gap GO/NO-GO (Sprint 18)"
baked_decisions:
  - "ADR-027 — egress policy"
  - "ADR-028 — measured-boot attestation scope"
  - "sizing: orchestrator-owned — run the full cluster in parallel, do not hand the LA a sequencing fork"
  - "key-recovery (§5.5): a parallel stream this sprint"
---

# Sprint 17 SDV — "The Boot Cluster"

## 1. Mission

Make the **real production boot path exist** (the guest↔host VM boundary), **build the decided egress
machinery**, and **lock the burned boot/posture seams with automation** — so the #598 air-gap-removal
gate (Sprint 18) is a *scripted audit*, not a manual boot marathon. This is the penultimate wave toward
#598; the air-gap stays UP throughout.

## 2. Where this sits — the #598 gate scorecard (SECURITY_ROADMAP §5, verified 2026-06-07)

DONE: 5.4 (no listener), 5.7 (audit stream — retention #607 deferred), 5.8 (boot ordering),
5.11 (dev-mode interlock); 5.9 **DECIDED → ADR-028**; 5.10 **DECIDED → ADR-027**.
This sprint advances/closes: **5.1** (production-posture verification automation), **5.2/5.3**
(egress machinery), **5.5** (key-recovery path), **5.6** (FUT-04 ceremony + flip).
Remaining for Sprint 18: the production-posture SWAGR sweep + the **5.12** LA sign-off (the gate itself).

## 3. Decisions BAKED — builders never stop to ask

Every scope call is already made and recorded; the wave executes against them:
- **Egress posture = ADR-027.** Deny-by-default allowlist (Kagi first, grown per-feature); the Policy
  Agent (PA) auto-approves within the allowlist + logs every call; kill-switch default-off + auto-trip on
  anomaly + LA-only re-arm; every outbound payload screened for secrets/PII and **blocked** on detection.
- **Attestation scope = ADR-028.** Security-material validation IS the #598 bar; true TPM PCR measured-boot
  is deferred to post-gate hardening (#627). Do NOT build PCR measured-boot this sprint.
- **Sizing = orchestrator-owned.** Run the full cluster in parallel (below). This is not an LA fork.
- **Key-recovery (§5.5) = a parallel stream this sprint** (gate-critical + disjoint).
- **#106/FUT-04** is CLOSED this sprint by the on-chip ceremony + flip (the BUILD was staged in Sprint 16).

## 4. Success criteria (the SWAGR audits against these)

| # | Criterion | Gate ref | Verification | Tier |
|---|---|---|---|---|
| **C1** | **#615 guest boundary** — the Windows `AF_HYPERV` addressing bug fixed; the dormant AF_HYPERV path in `vsock.py`/`transport.py` activated; the `launcher/__main__.py:927` `gateway_host_mode` topology flip wired with a clean fallback; a real-Hyper-V guest↔host round-trip test written | §5 (D-2: before #598) | unit/stub green in the gate; the real-VM round-trip is **hardware-marked**, green in the LA on-chip session | hw-batched |
| **C2** | **Full production-mode boot integration test** — the composed cascade (cert-mint → PA → AO → mTLS handshake → preflight → prompt → teardown) automated against the post-#615 topology | §5.1 | stubbed-GPU tier green in the gate; model-loaded tier hardware-marked + batched | mixed |
| **C3** | **ADR-027 egress machinery (STAGED/DORMANT)** — allowlist-widening mechanism + PA `DENY_EXTERNAL_NETWORK` carve-out (allowlisted + PA-adjudicated) + anomaly auto-trip + exfil screen (block-on-detect) + 4 mechanism locks; ships dormant (allowlist stays loopback+vsock; enforces only post-#556) | §5.2/5.3/5.10 | mechanism locks green with stubs; a "what activates this / how to add an allowlist entry" doc | gate |
| **C4** | **Security-cascade integration test (GAP-7)** — one automated walk of provision-key → cert-gen → boot → per-boot mint → mTLS handshake → TPM-signed audit record | §5.1 | SoftwareSealer stand-in tier green in the gate; real-TPM tier hardware-marked | mixed |
| **C5** | **Production-posture runtime guard (GAP-12 / #600)** — a test that boots production posture and asserts `dev_mode=false` at RUNTIME (the dynamic complement to the static secure-defaults locks) | §5.11 | green in the gate (slow-marked if it needs a real boot) | gate/slow |
| **C6** | **Offline key-recovery path (§5.5)** — recover the at-rest DEK from the offline recovery key after TPM/chip loss or hardware migration + a tested-recovery lock (a fresh environment decrypts via the recovery key) | §5.5 (gate-critical) | green in the gate (stand-in sealer) | gate |
| **C7** | **#106/FUT-04 close** — the manifest-signing ceremony runbook executed (LA on-chip, 4th TPM key `BlarAI-Manifest-Signing`) + `require_signed_manifest=true` flipped + a clean production boot verified with signing active | §5.6 | the ceremony + flip + boot are the LA on-chip session | hw-batched |
| **C8** | **Sprint-16 deferred green-baseline** — the boot-cascade smoke (#6(ii)) + the WinUI GUI tiers (#621) run GREEN (the kickoff prerequisite — committed≠done closure) | Sprint-16 carry | the LA on-chip session, FIRST (lock-before-modify) | hw-batched |
| **C9** | **Close hygiene** — §5 gate-tracker reconciled to what S17 closed; the standing gate (2212+) stays green, zero regressions; SCR + independent Auditor SWAGR + ledger land; #628 closed | — | the gate re-run by the Orchestrator + the Auditor independently | gate |

## 5. Scope / out-of-scope

**In:** C1–C9 above.
**Out (deferred, named so nothing silently slips):** true PCR measured-boot (**#627**, post-gate per
ADR-028); audit retention policy + signing authority (**#607**, Sprint 18, not gate-blocking); the
production-posture SWAGR sweep + GAP-5/6/8/9 model-loaded automation (**Sprint 18**, the pre-gate sweep);
the #598 sign-off itself (**Sprint 18**); #556 network features (post-gate); #626 `tools/tests` collection
errors (low-priority tooling). The egress machinery is BUILT but **does not enforce** until web features
ship post-#556 — the air-gap stays welded this sprint.

## 6. The parallel wave — max productivity, disjoint working sets

**Run as many worktree builders concurrently as the disjoint working sets allow.** The execution session
owns the final builder count and **may split any heavy stream for more parallelism** (e.g. the egress
machinery H below — split allowlist+auto-trip from the PA-carve-out+exfil-screen if it speeds the wave;
Sprint 16 split its heaviest stream by LA-approved precedent).

| Stream | Criterion | Working set (verified disjoint) | Start |
|---|---|---|---|
| **G1 — #615 (spine)** | C1 | `shared/ipc/vsock.py`, `services/ui_gateway/src/transport.py`, `launcher/__main__.py` (\~:927 topology region) | immediately |
| **G2 — boot integration test (spine)** | C2 | `tests/integration/` (new file) | after G1 merges (needs the live topology for the real tier) |
| **H — egress machinery** | C3 | `shared/security/egress_guard.py`, PA `rule_engine` (carve-out), new exfil-screen module, PGOV PII path, `services/*/config` | immediately (splittable) |
| **I — security-cascade test** | C4 | `tests/integration/` (new file), `shared/security` (read-mostly) | immediately |
| **J — production-posture guard** | C5 | `tests/security/test_production_posture.py` | after G2's boot-smoke infra exists (soft) |
| **K — key-recovery path** | C6 | `shared/security/dek_envelope.py`, recovery-key store, tests | immediately |

**Coordination (assign, don't race):** `launcher/__main__.py` — G1 (topology \~:927) vs H (egress arm
\~:1131): different regions, assign. `tests/integration/` — G2 + I add **distinct** files; J adds to
`tests/security/`. `shared/security/` — H (`egress_guard`), I (read-mostly), K (`dek_envelope`): different
files. Branch-guard (`branch==main` + toplevel) before EVERY main-tree merge — the worktree-cwd-branch
hazard bit this project 3×.

## 7. The LA on-chip track (ONE batched session — novice-runbooked, Orchestrator-driven, one command at a time)

The irreducible-human work, batched to minimize the LA's terminal time:
1. **FIRST — the green-baseline runs (C8):** the boot-smoke (#6(ii)) + GUI (#621) — lock the cascade
   *before* the wave's #615/egress edits are confirmed live. One command each.
2. **The #615 real-Hyper-V verify boot (C1):** boot the guest topology; paste the `launcher.log`.
3. **The FUT-04 manifest ceremony (C7):** the 4th TPM key via `docs/runbooks/manifest_signing_ceremony.md`
   (≤3 copy-paste full-path commands, public-key output only, idempotent); then the Orchestrator flips
   `require_signed_manifest=true` and confirms a clean boot.
Everything verifiable without the GPU/VM is driven green by the fleet first — this session is confirmation.

## 8. Gate-honesty conditions (non-negotiable — the "mocks pass, seams break" discipline)

- **Committed ≠ done until green.** C1 (real-VM), C2 (model-loaded tier), C7 (flip), C8 (baseline) ship
  BUILT + SCRIPTED; their first green run is the LA on-chip session. They get an explicit home on the SCR
  AND must not silently slip.
- **The egress machinery (C3) is staged/dormant** — it changes NO runtime behavior this sprint (allowlist
  stays loopback+vsock; enforces only post-#556). Same staged pattern as manifest signing.
- **#106/FUT-04** moves from PARTIAL to CLOSED only when C7's ceremony + flip + boot are green — not before.
- **The standing gate** (`shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware
  and not winui and not slow"` = 2212+) is re-run by the Orchestrator at every merge and reproduced by the
  Auditor — never trusted from a builder summary.

## 9. Merge-gate + the close (DEC-15)

- **Merge gate:** review each builder's diff against its criterion + **RE-RUN the gate yourself**; branch-
  guard before every main-tree merge; `--no-ff`, keep branches; no destructive git; never pytest against
  the live `%LOCALAPPDATA%` (the root `conftest.py` redirects it); pass EVERY field on `update_task` (#625).
- **The close:** fold journal fragments → `BUILD_JOURNAL.md`; author the SCR
  (`docs/sprints/sprint_17/strategic_completion_report.md`); run the **independent Auditor SWAGR** (manual
  spawn, model opus, adversarial — the Sprint-15/16 pattern); ledger entry in `docs/ledger/`; reconcile the
  §5 gate-tracker; close **#628**. Carry forward whatever stays open (the hardware-batched green runs if not
  yet executed; #607; the Sprint-18 pre-gate sweep).

## 10. Scope checkpoint (minimal-LA governance)

Per the LA's minimal-involvement directive, there is **no separate SDV sign-off ceremony**. The scope
checkpoint is the **execution session's comprehension gate**: it reads this SDV + the prep brief, presents
its understanding + planned wave, the **guide session reviews it** and hands the LA a paste-ready
confirm/correct. The LA's touches this sprint: launch the execution session, confirm the gate (via the
guide), the one on-chip session (§7), and the close. Everything else runs autonomously.

**Refs:** `docs/handoffs/sprint17-kickoff-prep.md` (the gate scorecard + working-set analysis);
ADR-027, ADR-028; SECURITY_ROADMAP §5; the Sprint-16 SDV + SCR + SWAGR (the wave pattern); #615, #619,
#600, #627, #106, #607.
