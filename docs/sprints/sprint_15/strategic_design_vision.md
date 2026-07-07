---
sprint_id: 15
sprint_name: "Tier-2 Production Posture — Per-Boot mTLS + Dev-Mode-Off Flip"
predecessor_sprint_id: 14
vikunja_tracking_task_id: 616
start_date: "2026-06-06"
target_completion_date: "2026-06-08"   # LA estimate; \~1-2 days agent wall-clock, not a hard deadline
la_approved_on: "2026-06-06T12:12:23-07:00"  # LA sign-off (v4 — flip-timing locked; v2 original 2026-06-06T09:31:58-07:00)
la_approved_by: "blarai"
co_lead_drafted_on: "2026-06-06T08:34:03-07:00"
co_lead_commit_when_drafted: "66f580f"
sdv_version: 4
---

# Strategic Design Vision — Sprint 15: Tier-2 Production Posture — Per-Boot mTLS + Dev-Mode-Off Flip

## 1. Executive brief

Sprint 15 builds BlarAI's **production-security layer** — the gate-critical step that makes the system's "working" posture the one that actually ships. We generate **per-boot mutual-TLS (mTLS) certificates** for the host↔VM vsock channel, and we **flip dev-mode off**, which activates the audit-stream TPM (Trusted Platform Module) signing and the JWT (JSON Web Token) signing keys that have sat *provisioned-but-dormant* on the security chip since Sprint 14. "Done" = the per-boot cert machinery built and verified **host-local at production posture** (real certs, `dev_mode=false`, real handshake), the dev-mode-off flip landed behind a regression lock, and **one on-chip ceremony + one production-posture live-verify** run by the Lead Architect (LA) that brings audit + JWT signing live. Per the LA's ratified Q1 decision, the full guest↔host VM-boundary handshake is **deliberately deferred** (tracked as #615) to the sprint that stands up a real VM occupant — Sprint 15 claims only what host-local evidence proves.

## 2. Context

### 2.1 Predecessor sprint outcome

- Predecessor SCR: `docs/sprints/sprint_14/strategic_completion_report.md`
- Predecessor SWAGR: `docs/sprints/sprint_14/Strategic_Work_Analysis_and_Gap_Report_Sprint_14_20260605_swagr.md`
- Sprint 14 delivered at-rest encryption (both SQLite stores under a TPM-sealed Data-Encryption Key + offline recovery key) and the audit-stream TPM **signer code**, live-verified for encryption; the independent audit returned **PASS, 7/7 criteria MET, 0 CRITICAL, 0 MAJOR, 4 MINOR (all closed)**. It intentionally left **one open thread that is this sprint's entire reason to exist**: the audit-TPM and JWT signing are wired but **dormant**, honestly named not claimed, gated on the dev-mode-off flip. Sprint 14 SWAGR MINOR-3 (store factory fail-open) was already closed by EA-7 (`e16450e`); it is **not** re-opened here.

### 2.2 Repo state at kickoff

- Main branch HEAD: `66f580f`
- Most recent ledger entry: `docs/ledger/20260606_010000_sprint14_scr_at-rest-encryption.md` (Sprint 14 close)
- Open Vikunja `Gate:Pending-Human` gates: this sprint's tracking task **#616** (pending SDV sign-off)
- Known-active feature branches: none (clean `main`; all Sprint-14 EA branches merged)

### 2.3 External inputs driving this sprint

- **LA asks / campaign**: the air-gap-removal campaign toward the **#598 GO/NO-GO gate**; the roadmap §6 Decision 3 (HYBRID VM topology) + Decision 8 (production-by-default dev-mode posture + network-facing interlock).
- **LA kickoff decisions (binding)**: Q1 = **fidelity-2** (host-local mTLS verify now; guest-boundary deferred) + three gate-honesty conditions (see §5.3, §9).
- **User-memory invariants**: production posture is the *only* "works" for #598; committed ≠ done until live-verified + merged; escalate capability/quality decisions, proactively fix defects.
- **ADR/DEC in play**: new **ADR-026** (per-boot mTLS + ephemeral cert provisioning) to be authored; cites ADR-021 (TPM-sealed PA JWT key — the cascade), ADR-025 (at-rest, predecessor), ADR-020 (egress kill-switch — verified armed), ADR-018 (TPM trust root). Note: ADR-023 is the *provenance* model and is **not** the certs ADR.

## 3. Sprint purpose

This sprint closes the **dev-mode-as-default trap** the LA named: today the launcher silently forces host services into dev-mode (`dev_mode_guard.py:90-91` resolves `HOST → True`), so every green test and every "BlarAI works" report has validated a *relaxed* configuration that would never ship — green on a posture that is not the production one. Flipping the running default to production (`dev_mode=false`) is what makes the test suite, the audit stream, and the JWT mint mean what they claim. Without it, the #598 gate cannot be evaluated honestly: the gate's controlling criterion is that Tiers 1–3 are verified **in the production posture**, and a dev-mode pass does not count.

The flip is **not a toggle** — it is a precondition cascade. With `dev_mode=false`, the Policy Agent **refuses to start** unless a weight manifest, the JWT TPM key + CA cert path, and a Known-Good Manifest are all present (`entrypoint.py:720-789`). So "flip dev-mode off" really means: build the per-boot certs the channel needs, stage a manifest so the boot cascade is satisfiable, run the on-chip ceremony that mints the JWT key, and only then verify the production boot. The dormant audit + JWT signing keys from Sprint 14 come alive at exactly this moment — this is where Sprint 14's deferred work gets its real-key live-verify.

The per-boot mTLS certificates are the second half: the hybrid VM topology (Decision 3) puts hostile web content behind a vsock boundary secured by mTLS with freshly-issued, short-lived certificates. We build that cert machinery now and verify it host-local (fidelity-2). The genuine VM-boundary handshake waits for a real occupant — there is no production VM↔host traffic to secure until web-nav exists, and the guest deployment channel is currently unproven.

If we skipped this sprint: the #598 gate stalls indefinitely (no production-posture verification possible), the chip-provisioned audit/JWT keys stay dormant, and the campaign cannot advance to Tier-3 or the gate review.

## 4. Success criteria

1. **Per-boot mTLS cert generation exists and is exercised.** A certificate authority (CA) plus per-boot ephemeral certificate issuance (and rotation) for the vsock channel. *Verification: code on `main`; unit tests for per-boot issuance + rotation green; the existing fail-closed lock `shared/tests/test_ipc_transport.py::test_transport_connect_no_mtls_production_fails` (line 366) is **extended** to cover per-boot issuance/rotation.*
2. **Dev-mode-off flip MECHANISM built + locked; shipped default stays dev.** EA-2 lands the resolver-inversion *capability* (production cleanly resolvable via the existing override seam), preserves the explicit `dev_mode=true` opt-in (loud, air-gapped — the permanent escape hatch), applies the test-blast-radius overrides, and lays the regression locks — but the **shipped running default remains dev through EA-1/2/3** (no live flip, so no brick window). *Verification: four mechanism locks green — (a) the shipped HOST default is still dev (the flip has NOT fired prematurely); (b) an explicit production signal resolves `dev_mode=false`; (c) the explicit dev opt-in resolves dev-mode (loud banner fires); (d) the interlock refuses `dev_mode=true + network_facing=true`; the suite green with the overrides applied. (Activation + the "HOST resolves production" proof move to criterion #8.)*
3. **Precondition cascade satisfied for a clean production boot.** A **minimal** Known-Good Manifest is staged and the JWT cert/key config resolves so the Policy Agent passes config-validation at `dev_mode=false`. *Verification: the full cascade runs green at `dev_mode=false` in an **off-chip software-stub-signer harness** (manifest + JWT key/CA paths + KGM path + stub-signed audit/JWT) — explicitly NOT full FUT-04 (see §5.2). This de-risks the cascade before the chip, narrowing on-chip surprises to the real-TPM-key-backed signing (see §9.1).*
4. **Fidelity-2 production live-verify (LA, on-chip).** With real per-boot certs and `dev_mode=false`: a host-local `CERT_REQUIRED` mTLS handshake **succeeds** with valid per-boot certs and **fails closed** with absent/invalid certs; and the `dev_mode=false` boot brings **audit-TPM signing + JWT signing live** (a signed audit record and a TPM-signed JWT are produced). *Verification: a live-verify evidence artifact recorded under `docs/security/` and/or `PERFORMANCE_LOG.md`; claims scoped exactly to the host-local machinery — no "production-verified" phrasing broader than what was exercised (LA Condition 2).*
5. **Ceremony honesty.** Before any provisioning, the on-chip key inventory is surfaced to the LA: the DEK seal key + audit signing key were already provisioned by the Sprint-14 at-rest ceremony (`provision_dek_keystore.py` step 3, idempotent `ensure_key`); the **JWT signing key is the net-new ceremony** (`provision_signing_key.py`). Ceremonies are idempotent + clobber-guarded. *Verification: the ceremony-prep output + the live-verify record.*
6. **New ADR-026 authored and accepted** — per-boot mTLS + ephemeral certificate provisioning (BlarAI namespace; next free number), **recording as a known limitation** that Sprint-15 per-boot certs are fresh-per-boot but **not yet measured-image-CN-bound** (FUT-02's full vision, deferred with measured-boot): *freshness* is proven, *issuer-attestation* is not. *Verification: `docs/adrs/ADR-026-*.md` on `main` with the limitation section present.*
7. **Gate-honesty obligations tracked, not silently closed.** The deferred guest-boundary handshake (#615) and full FUT-04 weight integrity (#106) are recorded as remaining #598 criteria. *Verification: #615 exists; #106 bound via comment; SDV §5.2 lists both.*
8. **Activation + daily-driver continuity (the flip's FINAL, gated step).** Production becomes the running default as the **final action inside EA-4**, only after EA-3's manifest is staged AND the ceremony has provisioned the keys — so the **first** production-default boot succeeds (no brick window; the default is dev until everything is present). *Verification (EA-4, LA on-chip): boot 1 (activation) brings audit-TPM + JWT signing live over the auto-minted per-boot certs; boot 2 — zero manual steps — proves daily-driver continuity; a regression lock asserts `resolve_dev_mode(HOST)` now resolves production post-activation.*

## 5. Scope

### 5.1 In-scope

1. **Per-boot mTLS certificate generation** — CA + ephemeral per-boot issuance/rotation for the vsock channel, plus **ADR-026**. Advances FUT-01 (#103, CA key storage) + FUT-02 (#104, ephemeral per-boot certs). [EA-1]
2. **Extend the fail-closed mTLS lock** (`test_ipc_transport.py:366`) to cover per-boot issuance/rotation. [EA-1]
3. **Dev-mode-off flip MECHANISM (no live flip) + escape hatch** — build the resolver-inversion *capability* (production cleanly resolvable via the existing override seam at `dev_mode_guard.py:88-93`, applied at `entrypoint.py:594-596`), keep the interlock + loud banner, **leave the shipped HOST default = dev** (the live flip is EA-4's final activation), and add the mechanism regression locks (criterion #2). Preserve + test + document `dev_mode=true` as the **permanent** explicit, loud, air-gapped (`network_facing=false`) opt-in, plus a one-line note on staying in/returning to dev post-activation (the opt-in, not brick-recovery — there is no brick under the deferred plan). Apply the **test-blast-radius overrides** so the suite survives EA-4's flip. [EA-2]
4. **Precondition cascade + off-chip stub harness** — stage a **minimal** Known-Good Manifest, wire `jwt.tpm_key_name` + `jwt.ca_cert_path` to the ceremony artifacts, ensure the KGM path resolves, so PA boots clean at `dev_mode=false`; build a **software-stub-signer harness** that runs the full `dev_mode=false` cascade off-chip (stub audit/JWT signers) so the cascade is proven green before the LA's on-chip session. [EA-3]
5. **Substrate micro-item (ratify)** — keep the substrate store's graceful-degradation posture (production + missing keystore → refuse the weak sealer + disable substrate memory loudly; confirmed fail-closed at `entrypoint.py:1090-1105`); **tighten the misleading comment at `entrypoint.py:1012-1014`** ("symmetric with `build_session_store`" — it is symmetric in *refusing the weak sealer*, asymmetric in *halt-vs-degrade*). [EA-3]
6. **Ceremony + ACTIVATION + fidelity-2 production live-verify** — JWT key ceremony (net-new), confirm DEK+audit keys present, **throw the running-default flip (the final activation, HOST→production) now that EA-3's manifest + the ceremony's keys are present**, then the host-local mTLS handshake + the two `dev_mode=false` boots (boot 1 brings audit/JWT signing live over the auto-minted certs; boot 2 proves zero-manual continuity). LA on-chip step. [EA-4]

### 5.2 Out-of-scope (deliberately deferred) — each with its tracked ticket

1. **Guest↔host AF_HYPERV boundary handshake (fidelity-3)** — **#615**, inherited by the VM-occupant sprint. *Why:* the guest deployment channel is unproven (`priority5_guest_deploy.json` = FAIL, \~3.5 months stale) and Alpine has no init wired; fixing that is multi-day infra that belongs with a real occupant.
2. **Full FUT-04 weight integrity** (`require_signed_manifest=true` + integrity-verify ALL model weights at load) — **#106**. *Why:* a separate Tier-3 #598 criterion; Sprint 15 stages only a *minimal* boot manifest. (LA Condition 3.)
3. **Relocating real services into the VM** — no occupant exists yet (web-nav is post-gate); building an empty quarantine box is capability-ahead-of-need.
4. **Full Known-Good Manifest provisioning ceremony** — FUT-05 (#107).
5. **Certificate revocation + epoch propagation** — FUT-03 (#105); build per-boot issuance now, revocation later.
6. **Egress per-action mediation + exfil-screen + kill-switch arming for web tools** — Tier-3, post-occupant. (The egress kill-switch itself is already armed: `launcher/__main__.py:944`, verified.)
7. **The Cleaner (UC-003)** — #613 (deferred from the gate per LA comment 889).
8. **Pluton-sealing the CA key / measured-image CN binding** — the full FUT-01/FUT-02 vision; Sprint 15 does software/TPM-backed per-boot certs verified at fidelity-2. ADR-026 records this as a known limitation: *freshness* (fresh-per-boot) is proven, *issuer-attestation* (measured-image CN binding, deferred with measured-boot) is not.

### 5.3 Scope boundaries and edge cases

- **Substrate factory:** ratify, do not re-architect — only the comment changes; the halt-vs-degrade asymmetry is an availability call, deliberately kept (AO starts, memory off, loud).
- **Minimal manifest:** just enough to satisfy the boot cascade; `require_signed_manifest` stays `false` (missing `.sig` permitted with a warning; present-but-invalid still fails closed). Not FUT-04.
- **mTLS:** build + host-local verify only; no AF_HYPERV guest binding claimed (LA Condition 2 — the live-verify states exactly what is and is not exercised).
- **No new dependencies** without LA approval; `cryptography` is already a project dependency.
- **The flip is thrown once, in EA-4:** EA-2 builds the mechanism but never changes the shipped running default; the running-default flip to production is EA-4's final activation, after the manifest (EA-3) + the ceremony's keys are present — so there is no brick window.

## 6. Deliverable summary

| Deliverable | Type | Target location | Success criterion |
|---|---|---|---|
| Per-boot mTLS cert generation (CA + issuance/rotation) | code | `shared/security/` (+ `shared/ipc/`) | #1 |
| Extended fail-closed mTLS lock | test | `shared/tests/test_ipc_transport.py` | #1 |
| ADR-026 — per-boot mTLS + ephemeral cert provisioning | doc | `docs/adrs/ADR-026-*.md` | #6 |
| Dev-mode-off flip + regression lock | code + test | `launcher/`, `shared/security/dev_mode_guard.py`, tests | #2 |
| Minimal Known-Good Manifest + JWT cert/key wiring | config + code | `services/policy_agent/config/`, `models/` | #3 |
| Substrate comment tightening | code (comment) | `services/assistant_orchestrator/src/entrypoint.py` | #5 (boundary) |
| Ceremony-prep + fidelity-2 live-verify evidence | doc/evidence | `docs/security/`, `PERFORMANCE_LOG.md` | #4, #5 |
| Dev-mode escape hatch + rollback note | code + test + doc | `launcher/`, `dev_mode_guard.py`, ADR-026 ops | #2, #8 |
| Off-chip stub-signer cascade harness | test | `tests/` (PA `dev_mode=false` boot harness) | #3 |
| Daily-driver continuity (2nd post-ceremony boot) | evidence | `docs/security/` live-verify | #8 |
| BUILD_JOURNAL entry + ledger close | doc | `docs/journal_fragments/`, `docs/ledger/` | (all) |

## 7. EA milestone plan

| EA-# | Working title | One-sentence purpose | Depends on | Approx size |
|---|---|---|---|---|
| EA-1 | Per-boot mTLS cert generation + ADR-026 | CA + ephemeral per-boot cert issuance/rotation for vsock; extend the fail-closed lock; author ADR-026 | main | M/L |
| EA-2 | Dev-mode-off flip MECHANISM (no live flip) | Resolver-inversion capability + escape hatch + test-blast-radius overrides + mechanism locks; **shipped default stays dev** (flip is EA-4) | EA-1 (∥ EA-3) | S/M |
| EA-3 | Cascade + stub harness + substrate ratify | Minimal KGM + JWT cert/key wiring + KGM path; off-chip stub-signer cascade harness; ratify substrate degradation + fix comment | EA-1 | M |
| EA-4 | Ceremony + ACTIVATION + fidelity-2 live-verify (iterative) | JWT key ceremony (net-new), confirm DEK/audit present, **throw the running-default flip (final activation)**, host-local mTLS handshake + 2 `dev_mode=false` boots (boot1 audit/JWT live; boot2 zero-manual continuity); may take 1-2 cycles | EA-1, EA-2, EA-3 | M (LA on-chip) |

**Sequencing (v4 — flip-timing locked):** EA-1 (certs) → { EA-2 *mechanism* ∥ EA-3 *manifest* — working-set-disjoint (EA-2 = launcher/resolver mechanism; EA-3 = config/manifest/substrate), both branch off EA-1-merged `main`, may run in parallel } → EA-4 (ceremony + **activation** + 2-boot live-verify). EA-2 builds the flip mechanism but **does not throw it** — the running-default flip is EA-4's FINAL action, and it never fires while the manifest/keys are absent (so there is no brick window). EA-1's per-boot mint is `if not _dev_mode:`-gated (`launcher/__main__.py:493`), so it stays dormant until EA-4 activation. (EA-2 still edits the launcher comment region + `dev_mode_guard.py`, so it branches off EA-1-merged main to avoid a launcher conflict; it is disjoint from EA-3's config/substrate working set.)

## 8. Dependencies and prerequisites

### 8.1 Upstream dependencies

- Predecessor SCR (done). The Sprint-14 at-rest ceremony having provisioned the DEK seal key + audit signing key **on this chip** — confirmed in code; to be re-confirmed on-chip in EA-4 ceremony-prep before the flip.
- `cryptography` library (already present in the 3.11 venv).

### 8.2 External dependencies

- A real **TPM 2.0** (Microsoft Platform Crypto Provider) on the deployment host — the ceremony fails closed without it. This is the LA's machine.
- One **LA on-chip ceremony/live-verify session** (private terminal, never a Claude session — secrets must not hit a transcript).

### 8.3 Assumed invariants

- The vsock mTLS code path (`shared/ipc/vsock.py` — `VsockListener`, the SSL-context factories) is stable for the sprint.
- The dev-mode override seam (`dev_mode_guard.resolve_dev_mode` + the service-side application) is stable.
- `default.toml` config keys (`inference.weight_manifest`, `jwt.tpm_key_name`, `jwt.ca_cert_path`, `ipc.mtls_*`) are stable. If any changes, a CAR loop is warranted.

### 8.4 Parallel-Sprint Authorization & Shared-Artifact Audit

**N/A — serial kickoff (no other sprint active).** `docs/active_tasks.yaml` is empty at kickoff; no concurrent sprint overlaps. No shared-mutable cross-sprint artifact audit required.

## 9. Risks and unknowns

### 9.1 Known risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| The flip touches the boot path; a regression could refuse-to-start in production | Med | High | Stage the cascade (EA-3) before the flip activates; regression lock (criterion #2); **the preserved `dev_mode=true` escape hatch + rollback note are the way back in** if a production boot blocks daily use; EA-4 verifies the clean boot |
| Ceremony/live-verify needs the LA's chip and can stall the sprint | Med | Med | Batch into one on-chip session; ceremony-prep surfaces the exact key inventory first; **EA-3's off-chip stub-signer harness de-risks the cascade before the chip, so the on-chip live-verify may be iterative (1-2 cycles) but narrowed to the real-TPM-key signing** (reconciles §9.3) |
| Per-boot cert rotation edge cases (lifetime, clock, reuse) | Med | Med | Unit tests for issuance + rotation; extend the fail-closed lock; ADR-026 records the lifetime decision |
| **Scope blur** — fidelity-2 over-claimed, or the minimal manifest mistaken for FUT-04 | Med | High | LA Conditions 2 & 3 enforced in the live-verify wording + §5.2; #615 and #106 tracked as remaining gate criteria |
| Guest-channel temptation (someone tries to "just verify in the guest") | Low | Med | Explicitly out-of-scope (#615); the guest channel is unproven, not a Sprint-15 dependency |

### 9.2 Known unknowns

1. Whether the Sprint-14 ceremony provisioned the audit key on **this specific chip** (verify in EA-4 ceremony-prep, before the flip).
2. The exact per-boot certificate lifetime / rotation cadence — decided in EA-1 and recorded in ADR-026.
3. Whether host-local vsock (CID 2) or a real TLS socket is the cleanest fidelity-2 harness — an EA-1/EA-4 implementation choice; the claim wording is fixed regardless (Condition 2).

### 9.3 Unknown unknowns posture

This sprint changes the **default security posture of the whole system** and lights up two dormant signing paths at once. The most likely surprise is a boot-path interaction the cascade map didn't capture — a config key required at `dev_mode=false` that isn't on the enumerated list, or a signing path that assumed a dev stub. The mitigation is sequencing (stage everything, then flip, then verify) and treating the first clean `dev_mode=false` boot as the real test, not the unit suite. We assume we have *not* found every production-only requirement by reading the code; EA-4's live boot is where the rest surface.

## 10. Alignment to long-term roadmap

- **Project phase alignment**: Phase 5 Post-Operational Development; **Tier-2 gate-critical** work on the air-gap-removal campaign; the production-posture step that makes #598 evaluable.
- **Use Case alignment**: UC-001 (Policy Agent) and UC-004 (Assistant Orchestrator) — the production posture both services run under; the JWT mint (UC-001 authorization artifact) goes live here.
- **ADR alignment**: authors **new ADR-026** (per-boot mTLS + ephemeral cert provisioning); confirms ADR-021 (TPM-sealed JWT key — the boot cascade), ADR-025 (at-rest, predecessor), ADR-020 (egress kill-switch — verified armed), ADR-018 (TPM trust root). Does **not** touch ADR-023 (provenance).
- **DEC alignment**: roadmap §6 Decision 3 (HYBRID VM topology) + Decision 8 (production-by-default dev-mode + network-facing interlock); DEC-15 sprint lifecycle.

## 11. Roles and accountability

| Role (cf-3 standardized) | Responsibility this sprint | Budget |
|---|---|---|
| **LA (Lead Architect)** | SDV sign-off; the on-chip ceremony + the one production-posture live-verify; CAR adjudication; SCR + SWAGR read | \~30–60 min interactive + one \~20–30 min on-chip session |
| **Orchestrator** (was Co-Lead) | EA prompt authoring, merge-gate review, milestone peer review, SCR | Autonomous within the merge gate |
| **Specialist subagents** (worktree builders) | EA-1..EA-4 execution in isolated worktrees | Per-EA, merge-gated |
| **Auditor** | Independent SWAGR at sprint close (manual invocation; fleet paused) | Autonomous per DEC-15 |

## 12. Estimated effort

- **Rough duration**: \~1–2 days agent wall-clock; 4 EA milestones (EA-1 ∥ EA-2, then EA-3, then EA-4).
- **LA active-time**: \~30–60 min interactive (SDV sign-off + CARs + SWAGR read) **plus** one \~20–30 min on-chip ceremony/live-verify session — which **may run 1–2 iterative cycles** if production-only requirements surface (§9.3); EA-3's off-chip stub harness narrows the on-chip surprises to the TPM-key-backed signing.
- **Confidence**: **Medium** — the cascade and the ceremony are well-mapped on disk; the main variable is the per-boot cert rotation design (EA-1) and whatever the first real `dev_mode=false` boot surfaces (§9.3).

## 13. Deliberate non-goals

1. **Full guest VM service relocation** — *rejected because* no occupant exists yet; the VM's job (contain hostile web content) has nothing to contain until web-nav, which is post-gate.
2. **Full FUT-04 weight integrity this sprint** — *rejected because* it is a separate Tier-3 #598 criterion (#106); a minimal boot manifest is all the flip requires.
3. **Pluton-sealed CA / measured-image CN binding now** — *rejected because* per-boot software/TPM-backed certs verified at fidelity-2 are the right first increment; the sealed-CA hardening is FUT-01's full vision, later.
4. **Claiming "production-verified" for the guest boundary** — *rejected* (LA Condition 2); fidelity-2 evidence proves the host-local cert machinery only, and the live-verify says so explicitly.

## 14. Sign-off

### Lead Architect

> I, blarai, have reviewed this SDV on `<date at sign-off>`. I approve the sprint scope, success criteria, and risk posture as stated, including the fidelity-2 decision and the three gate-honesty conditions. I accept that the guest-boundary verification (#615) and full FUT-04 (#106) remain tracked #598 obligations not closed by this sprint. I will run the on-chip ceremony + production live-verify, and read the SCR and SWAGR when produced.

_(Signed via the frontmatter field `la_approved_on` above. A commit authored on `main` is the durable signature.)_

### Orchestrator (Co-Lead)

> The Orchestrator acknowledges the LA-signed SDV and will translate it into the EA-1..EA-4 prompts under the merge gate per the DEC-15 flow, holding the fidelity-2 claim discipline (Condition 2) and the minimal-manifest boundary (Condition 3). Any scope deviation arising during execution is flagged at the merge gate or escalated via a CAR.

_(Signed via `co_lead_drafted_on` + the git commit that lands this SDV on `main`.)_

---

## Appendix A — SDV revision log

| Version | Date | Changed by | Change summary |
|---|---|---|---|
| 1 | 2026-06-06 | Orchestrator (draft) | Initial draft for LA review — fidelity-2 + three conditions + precondition cascade baked in |
| 2 | 2026-06-06 | Orchestrator (pre-sign) | LA review additions: daily-driver continuity criterion (#8, ADD-1); dev-mode escape hatch + rollback as scope/risk (ADD-2); iterative on-chip live-verify + off-chip stub harness (refinement 1); ADR-026 freshness-not-attestation limitation (refinement 2) |
| 3 | 2026-06-06 | Orchestrator (post-sign) | §7 sequencing correction: EA-1 → EA-2 are sequential (shared `launcher/__main__.py` working set), not parallel — the v1/v2 "disjoint" note under-counted EA-1's launcher reach. No change to signed scope or success criteria. |
| 4 | 2026-06-06 | LA (SIGNED 2026-06-06T12:12:23-07:00) | Flip-timing LOCKED (scope change): criterion #2 re-scoped to MECHANISM-ONLY (shipped default stays dev); criterion #8 reconciled to ACTIVATION + continuity (flip is EA-4's final gated step); §7 EA-1 → {EA-2 mechanism ∥ EA-3 manifest} → EA-4 (ceremony+activation+2-boot); §5.1.3/5.1.6/5.3 aligned. Eliminates the dev-mode-off brick window. LA verified no early flip across all 8 criteria; ADD-1/ADD-2 intact. |
