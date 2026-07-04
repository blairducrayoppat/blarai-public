---
sprint_id: 17
sprint_name: "The Boot Cluster"
report: "Strategic Completion Report (SCR)"
status: "BUILD-COMPLETE + GATE-GREEN (host-independent invariant: 0 failed / 108 deselected / 2342 selected; 2340 passed / 2 skipped on the provisioned dev box, 2320 / 22 in a clean worktree — see §3). Close in progress (SWAGR done: STRONG_ALIGNMENT 0C/0M/5m → ledger → #628). Hardware-tier green runs + the LA on-chip session PENDING (committed ≠ done until green)."
tracking_task: 628
gate: "#598 air-gap GO/NO-GO (now Sprint-18 phase 7, after the #612 Capstone phase 6 — SECURITY_ROADMAP restructured by the LA 2026-06-07, commit 021ffda)"
authored_by: "Sprint-17 execution Orchestrator"
authored_on: "2026-06-07"
predecessor: "SDV docs/sprints/sprint_17/strategic_design_vision.md (148f3e1)"
main_head_at_report: "61f0daf (G2 merge)"
---

# Sprint 17 SCR — "The Boot Cluster"

## 1. Outcome

The Boot Cluster wave executed to plan: the **real production boot path now exists**
(the #615 guest↔host AF_HYPERV boundary, activated with a clean host-mode fallback),
the **ADR-027 egress machinery is built and shipped dormant** (the air-gap stays
welded), and the **burned boot/posture seams are locked with automation** so the
#598 gate becomes a scripted audit rather than a manual boot marathon.

Seven worktree builders ran concurrently against disjoint working sets and merged
serially under the Orchestrator-held merge-gate. The standing gate moved **2212 →
2340 on the dev box (+128 net new tests), green at every merge, zero regressions** —
host-independent invariant **0 failed / 108 deselected / 2342 selected** (the
passed/skipped split is host-dependent; §3). The heavy
egress stream (H) was split (H-a/H-b) for parallelism; the split's seam is verified
live (below). One merge-gate defect was caught and proactively fixed (the J
worktree-vs-main manifest seam, §7).

**Honesty line (SDV §8):** this report is BUILD-COMPLETE + GATE-GREEN. The
hardware-tier green runs (C1 real-VM, C2 model-loaded, C4 real-TPM, C7 FUT-04
ceremony+flip, C8 Sprint-16 baseline) are BUILT + SCRIPTED and **not yet green** —
their first green run is the one LA on-chip session (§4). Committed ≠ done until
green; #106/FUT-04 stays PARTIAL until C7 is green.

## 2. Criteria scorecard (SDV §4)

| # | Criterion | Stream | Merge | Gate-tier result | Hardware/deferred tier |
|---|---|---|---|---|---|
| **C1** | #615 guest boundary | G1 | `19ded19` | **MET** — AF_HYPERV addressing fix + dormant path activated + topology flip w/ clean host fallback; unit/stub green (gate +18) | real-VM round-trip `@hardware` → on-chip step 2 |
| **C2** | Full production-mode boot integration test | G2 | `61f0daf` | **MET** — composed prod cascade (cert→AO→mTLS handshake→preflight→teardown) executes green w/ stand-in material + GPU stub (gate +5) | model-loaded tier `@hardware` → on-chip / Sprint-18 |
| **C3** | ADR-027 egress machinery (STAGED/DORMANT) | H-a + H-b | `7034f9a`, `010bda6` | **MET** — allowlist-widening + auto-trip + PA carve-out + exfil screen + locks; **dormant** (live allowlist loopback+vsock; air-gap welded); seam verified live | — (enforces only post-#556) |
| **C4** | Security-cascade integration test (GAP-7) | I | `bacd5f3` | **MET** — provision→cert→mint→mTLS→TPM-signed audit walk; stand-in tier green | real-TPM tier `@hardware` (builder I *reported* green on the reference TPM; unverified in-tree — capture evidence at the run) → on-chip / Sprint-18 |
| **C5** | Production-posture runtime guard (GAP-12/#600) | J (+J-fix `22c2161`) | `475facd` | **MET** — runtime `dev_mode=False` assertion executes (gate +12); fixed to assert the security-material gate by invariant (§7) | real-boot tier `@slow` → on-chip / Sprint-18 |
| **C6** | Offline key-recovery path (§5.5) | K | `873f5b5` | **MET** — fresh-environment (dead-chip) recovery decrypts real at-rest data via the offline recovery key; stand-in tier green (gate +34) | (optional real-TPM recovery round-trip noted by K → on-chip) |
| **C7** | #106/FUT-04 close (manifest ceremony + flip) | on-chip | — | **PENDING** — runbook `manifest_signing_ceremony.md` exists; the 4th TPM key + `require_signed_manifest=true` flip + clean boot are the on-chip session | hw-batched → on-chip step 3 |
| **C8** | Sprint-16 deferred green baseline (#6(ii) boot-smoke + #621 GUI) | on-chip | — | **PENDING** — BUILT+SCRIPTED in Sprint 16; first green run is the on-chip session, FIRST (lock-before-modify) | hw-batched → on-chip step 1 |
| **C9** | Close hygiene | Orchestrator | (this report) | **IN PROGRESS** — gate 2340 green, zero regressions; SCR (this) → SWAGR → ledger → §5 reconcile → close #628 | — |

**C1–C6: MET for the gate tier (the buildable scope), all merged + gated green.**
**C7, C8: PENDING the on-chip session. C9: in progress.**

## 3. The merge-gate record

Standing gate selection: `shared/ services/ launcher/ tests/integration/ tests/security/ -m "not hardware and not winui and not slow"`, re-run with the `.venv` python by the Orchestrator at every merge (never trusted from a builder summary).

| After merge | Stream | Gate (passed) |
|---|---|---|
| baseline (SDV `148f3e1`) | — | 2212 |
| `873f5b5` | K | 2246 |
| `bacd5f3`+`475facd` | I + J (batched — pure test-additions) | (gated post-fix) |
| `22c2161` | J-fix | 2260 |
| `19ded19` | G1 | 2278 |
| `7034f9a` | H-a | 2311 |
| `010bda6` | H-b | 2335 |
| `61f0daf` | G2 | **2340** |

Final (host-independent invariant): **0 failed, 108 deselected, 2342 selected.**
The passed/skipped split is host-dependent: on the provisioned dev box (model
weights present) **2340 passed / 2 skipped** (~102s); in a clean git worktree (no
`models/`) **2320 passed / 22 skipped** — the 20-test delta is the semantic-router
suite, which needs an embedding model absent from a worktree (the same
`models/`-presence seam as the J-fix, §7). The load-bearing, host-independent
facts: **0 failed, +128 net new tests, zero regressions** vs the 2212 baseline.
(The independent Auditor reproduced 2320 / 22 / 108 / 0-failed in a clean worktree;
the per-merge counts above were measured on the dev box.)

Discipline held throughout: branch-guard (`branch==main` + toplevel) before every
main-tree merge; `--no-ff`, branches kept; no destructive git; live `%LOCALAPPDATA%`
redirected by the root `conftest.py`.

## 4. Gate-honesty: the hardware-batched tiers (committed ≠ done until green)

Every hardware/real tier has an explicit home — nothing left implicit (the guide's
sharpening #2). The **one batched LA on-chip session** (SDV §7), in order:

1. **C8 FIRST** — Sprint-16 boot-cascade smoke (#6(ii)) + WinUI GUI tiers (#621) — lock-before-modify (green the cascade before confirming the wave's edits live).
2. **C1** — the #615 real-Hyper-V guest↔host round-trip boot (`test_guest_boundary_hyperv.py`, `@hardware`). G1 confirmed the dev box's AF_HYPERV probe succeeds → a live guest path exists.
3. **C7** — the FUT-04 manifest-signing ceremony (4th TPM key `BlarAI-Manifest-Signing`) → Orchestrator flips `require_signed_manifest=true` → clean production boot. Closes #106.
4. **C2 model-loaded tier** (opportunistic while the real model is loaded) — `TestProductionBootCascadeRealModel`, else explicit defer → Sprint-18 model-loaded sweep.
5. **C4 real-TPM tier** (opportunistic while the TPM is engaged for the ceremony) — builder I reported it green on the reference TPM during the build (unverified in-tree, `@hardware`/deselected — capture the evidence artifact at the run); re-run wherever #598 is audited, else defer → Sprint-18.

## 5. Scope reconciliation (SECURITY_ROADMAP §5) — to finalize at close

The LA restructured the campaign sequence mid-sprint (commit `021ffda`, 2026-06-07):
tier verification (§5) → **#612 Capstone (phase 6, standalone)** → #598 sign-off
(phase 7) → #556 (phase 8). The §5 gate-tracker reconciliation (a close step, on the
post-`021ffda` doc) records what Sprint 17 advanced:

- **5.1** (production-posture verification automation) — advanced: C2 prod-boot integration + C5 runtime posture guard (gate tier green; model-loaded + full-boot tiers → on-chip/Sprint-18).
- **5.2 / 5.3** (egress controls / every egress through the PA) — machinery BUILT (C3), shipped dormant; enforces post-#556.
- **5.5** (offline key-recovery) — **MET** (C6, fresh-environment recovery lock green).
- **5.6** (FUT-04) — **PARTIAL until C7** (ceremony + flip on-chip).
- 5.9 / 5.10 already DECIDED (ADR-028 / ADR-027); 5.4/5.7/5.8/5.11 DONE pre-sprint.
- Remaining for the gate: the production-posture SWAGR sweep + GAP-5/6/8/9 model-loaded automation (Sprint 18), the #612 Capstone phase (now phase 6), then 5.12 sign-off (phase 7).

## 6. Carry-forwards

- **Hardware-tier green runs** (C1, C2 model-loaded, C4 real-TPM, C7, C8) → the one LA on-chip session (§4). Committed ≠ done.
- **#106 / FUT-04** stays PARTIAL until C7's ceremony + flip + boot are green.
- **#607** (audit retention policy + signing authority) — tracked LA decision, not gate-blocking.
- **Sprint-18 pre-gate sweep** — production-posture SWAGR across all tiers + GAP-5/6/8/9 model-loaded automation; then the #612 Capstone phase; then the #598 5.12 sign-off.
- **#626** (4 pre-existing `tools/tests/` collection errors) — low-priority tooling, outside the gate.
- **Doctrine-currency sweep** — CLAUDE.md Phase-History row (~line 252: stale "Sprint 10 ACTIVE / ~981 tests") to refresh; a close-hygiene edit.
- **Dependency hash-pinning lockfile** (GAP-14 follow-on) — pins landed Sprint 16; hashes pending.
- **State-hygiene cleanup** — ~33 stale Sprint-14/15 agent worktrees + branches (LA's approved inventory-not-delete action, whenever wanted).

## 7. Decisions / findings of record

- **The J merge-gate catch (gate-honesty in action).** J's AO production-gate test passed in its isolated worktree but failed on real main: it assumed the Known-Good Manifest was absent "in the test tree" — true in a `git worktree` (no `models/`), false on the provisioned dev box where the real manifest is present (the gate correctly accepts it under staged-OFF `require_signed_manifest=false`). Fixed (`22c2161`) to assert the production security-material gate by **invariant** (KGM *or* JWT CA), not a host-specific code. Runtime gate unchanged. Lesson: *a posture test must own the outcome it asserts on, not the host's provisioning state* (journal fragment `2026-06-07_sprint17-j-posture-fix.md`).
- **The H-split seam is in the LIVE boot path, and is verified.** `egress_guard.arm()` runs at every production boot (`launcher:1133`), so the screener-registration + auto-trip wiring is live even though external egress stays dormant. The seam test RUNS (not skips) on merged main: a simulated exfil detection fires `egress_guard.trip()` through H-b's registered screener (`TestExfilScreenSeamToEgressGuard`, 3/3 RUN+PASS). The guide's sharpening #1, satisfied.
- **`DENY_EXTERNAL_NETWORK` location (H-b finding).** The rule is RULE 3 of `DeterministicPolicyChecker.check()` in `services/policy_agent/src/gpu_inference.py` (enforced at BOTH the PA boundary AND the AO tool loop `_adjudicate_tool_dispatch`), NOT `rule_engine.py` as the SDV/brief named. The carve-out was placed there so one change covers both call sites; H-b self-caught + fixed a scheme-smuggling fail-open (carve-out restricted to http/https — ftp/ws/gopher stay denied even to an allowlisted host).
- **Egress dormancy (the air-gap is unchanged this sprint).** `egress_guard`'s active allowlist stays loopback + AF_HYPERV; the PA carve-out's `_EGRESS_ALLOWLIST` is empty → every external URL still hits DENY, byte-for-byte identical to today. The machinery enforces only once a web feature ships post-#556.
- **C2/C5 tier boundary (where the hardware line falls — not a capability decision).** The AO production gate is satisfiable off-chip with stand-in material; the PA production gate is irreducibly TPM-bound (provisioned JWT + audit keys, real model). So the gate tier composes the production cascade around the AO + the real mTLS handshake; the full-production PA boot is the hardware tier. Documented in the C2 test.
- **J moved to Wave 1 (sharpening #3).** C5's runtime guard builds on the service-construction APIs already on main, independent of G2 — so it ran concurrently rather than waiting on the G1→G2 spine.

## 8. Close checklist (C9 / DEC-15)

- [x] All 7 builders merged `--no-ff`, branches kept; gate green at 2340; zero regressions.
- [x] H-split seam verified RUNS-and-passes (not skipped) on merged main.
- [x] SCR authored (this document).
- [x] Fold journal fragments → `BUILD_JOURNAL.md` (8 build fragments) — done `d38a0c1`/`efd93df` (lessons 73-81). *Two on-chip-session fragments (`2026-06-07_sprint17-onchip-close`, `…_gui-harness-621-fixes`) await the next fold.*
- [x] Independent Auditor SWAGR (opus, adversarial) — done `ed860c8` (STRONG_ALIGNMENT, 0C/0M/5m).
- [x] Reconcile SECURITY_ROADMAP §5 gate-tracker — done `3bd4107`/`65d66f4`.
- [x] Doctrine-currency sweep (CLAUDE.md Phase-History row) — done `3bd4107`.
- [x] Ledger entry in `docs/ledger/` (per-file, DEC-17) — build-close `…180000…`; on-chip-close `20260607_224258_sprint17-onchip-close.md`.
- [ ] Close #628 — on-chip hardware tiers now GREEN (§9 below); **OPEN pending the LA's independent verification**.

**Refs:** SDV (`docs/sprints/sprint_17/strategic_design_vision.md`); ADR-027, ADR-028; SECURITY_ROADMAP §5 (post-`021ffda`); the journal fragments under `docs/journal_fragments/`; #615, #600, #627, #106, #607.

## 9. On-chip session close (2026-06-07 22:42 local)

The §4 hardware-batched tiers are no longer deferred — they ran on the dev machine (real TPM 2.0, Arc 140V, Qwen3-14B) and are GREEN. Detail in `docs/ledger/20260607_224258_sprint17-onchip-close.md`; narrative in the on-chip journal fragment.

| Tier | SDV criterion | Result |
|---|---|---|
| **C7 / #106** | FUT-04 signed-manifest enforcement | **DONE** — ceremony + flip + signature-verified + gate-green + real boot cleared the manifest gate |
| **C8a** | Boot-cascade smoke, real model | **GREEN** (model-path fix) |
| **C8b / #621** | WinUI GUI harness | **GREEN** — 13/13 critical-path + 2/2 model-loaded |
| **C2** | Model-loaded production boot cascade | **GREEN** — cert-location fix; full real cascade; proven test-tier (not an mTLS gap) |
| **C4** | Real-TPM security cascade (GAP-7) | **GREEN** + evidence captured → **closes SWAGR MINOR-2** |
| **C1 / #615** | Guest-boundary AF_HYPERV round-trip | **DESIGN-PROVEN here; PENDING** the deployment round-trip (≥3.12 runtime + Alpine responder; #615) |

**Standing gate re-confirmed: 2342 passed / 0 failed** after every on-chip merge.

**C7 / FUT-04 — LOUD:** `require_signed_manifest = true` is **LIVE** in both service configs — production **fails closed** without a validly signed weight manifest. The manifest is signed (flip un-skipped 2 signed-manifest gate tests, now passing); 4th TPM key `BlarAI-Manifest-Signing` provisioned; trust anchor `508defe5c27c0f0f7e5477cb033180f6dad1de6c076b32ff8b015923137b5ae4`; reversible by one line.

**Finding of record (amends §7):** the #615 hardware run surfaced an alarm I **withdrew** — `connect(): bad family` is a Python-version gap (venv 3.11.9 predates `socket.AF_HYPERV`; system 3.14 has it and dials the guest), not a broken design. Phase-2 `vsock_validation.json` proves the real round-trip; the gateway is OpenVINO-free so it runs ≥3.12 cleanly. The "ctypes rewrite / #598 re-scope" framing is withdrawn; the fail-silent probe defect was fixed (now refuses to claim guest-mode loudly). Recorded on #615 (comment 925).

**On-chip commits:** `09c62b1` (FUT-04 + C8a + C1), `f4bdea4` (C2 + C4 evidence), `d3fe427` (GUI 13/13).
