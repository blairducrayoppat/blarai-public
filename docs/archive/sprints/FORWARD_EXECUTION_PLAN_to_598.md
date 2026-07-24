# Forward Execution Plan — Sprint 16 → the #598 air-gap gate → beyond

**Prepared:** 2026-06-07 by the outgoing orchestrator session (`7b65c3b8`), for the new lead to pick up **after** the Sprint-15 close. Built from two parallel code/doc surveys (a working-set disjointness map + the 9-Use-Case / post-#598 horizon), the security roadmap §3–§6, and the live Vikunja backlog.

---

## 0. How to use this

This is the strategic input for the next DEC-15 sprint kickoffs (SDV → execution → SCR → SWAGR). It is **not** a substitute for the per-sprint SDV — it sequences the remaining campaign and shows what is parallelizable, what is automatable, and what still needs the Lead Architect (LA). Each "wave" below becomes a sprint kickoff. The LA confirms scope at each kickoff; the open decisions are collected in §7.

---

## 1. Where we are (the controlling frame)

- **Sprint 15** (Tier-2: run-in-VM / mTLS / per-boot certs) is at its production live-verify — **boot-1 PASSED on real hardware**. The dev→production flip is active.
- **#598 is the controlling gate.** The air-gap comes down ONLY when all tiers are complete AND independently SWAGR-verified in **production posture** (`dev_mode=false`, real certs/keys) AND the LA signs off. *A dev-mode pass does not count toward the gate* (TEST_GOVERNANCE §2.5 / the mock-passes-prod-fails trap).
- BlarAI is a **decades-long platform.** #598 is the pivot (air-gap → guarded door), **not the end.** After it: #556 network capabilities, then the use-case roadmap UC-002 → UC-005 → … → UC-009.

---

## 2. The remaining work to #598

### 2a. STEP 0 — a verified roadmap-state reconciliation (before any building)

**We do not currently track "what's done vs. remaining" in one reliable place, and the campaign docs are partly stale.** `SECURITY_ROADMAP §5` has a gate-criteria checklist that is *meant* to be that tracker, but its checkboxes were never kept current — it still lists the "tamper-evident audit stream" + "measured-boot" as Tier-1-remaining when Sprint 13 shipped the hash-chained + TPM-signed audit stream (ADR-021) and the launcher already does measured-boot ordering; and it implies a manifest-signing ceremony that may not even be gate-required (§2c). **The first campaign task, before any building: walk every §5 gate criterion AND every TPM key, confirm its *actual on-disk state*, and update the §5 checklist into the current authoritative tracker — verified, not inherited from the doc.**

*Key state confirmed on disk 2026-06-07:* PROVISIONED — `BlarAI-DEKSeal`, `BlarAI-PA-JWT-Signing`, `BlarAI-Audit-Signing-Key-v1` (the three ceremonies are done). NOT provisioned — `BlarAI-Manifest-Signing` (the FUT-04 manifest key; the manifest is currently hashed-but-unsigned by design — see §2c). Likely genuinely-remaining Tier-1: the **PII-filter posture** + the **measured-boot *attestation policy*** (what a failed attestation does). This Step-0 reconciliation is read-mostly, not a build — and it is the durable answer to "are we tracking what's done."

### 2b. Tier-2 remainder — the #615 guest-boundary + a gate-scoping decision for the LA

Sprint 15 proved the host-local mTLS machinery at **fidelity-2**. The real **AF_HYPERV guest↔host VM isolation (#615)** is the remaining Tier-2 piece. The survey found the AF_HYPERV production path is **already written but dormant** behind `host_mode=False` (`shared/ipc/vsock.py`, `services/ui_gateway/src/transport.py::_connect_hyperv`) — so #615 is closer to **activate-and-verify** than build-from-scratch. Treat it with the same merge-gate + live-verify rigor as the routing path (a dormant path can hide the same kind of seam bug).

> **LA DECISION (gate-scoping, §7-2):** Is fidelity-2 (host-local mTLS) **sufficient for the #598 gate**, with the real VM boundary (#615) landing later with #556? Or must #615 land **before** #598? The HYBRID VM topology (Decision 3) puts network-facing code in the VM — so the guest boundary matters most once network code runs there (i.e., with #556). If the gate posture is "egress-only, no network features live" (Decision 7: ingress = none), fidelity-2 may suffice with #615 as the activation step that lands *with* #556. This changes the #598 scope — it's your call.

### 2c. Tier-3 — supply-chain + egress

- **FUT-04 full weight integrity (#106) — two halves, only one is a ceremony.** (a) **Verify all weights at load** — today only one `.bin` is hash-verified; extend the existing `verify_weight_integrity` sweep to every `.bin` in the manifest. **Code, no ceremony.** (b) **Signed manifest** (`require_signed_manifest=true`) — the manifest is currently *hashed but unsigned* (the boot logs "unsigned manifest accepted"). Signing it uses `BlarAI-Manifest-Signing` — a **4th, separate TPM key** (deliberately isolated from the DEK / JWT / audit keys, the same principle that split the audit key from the JWT key), **not yet provisioned** (it isn't even in the ceremony preflight). This is the one remaining ceremony — **but whether it is gate-required is a scoping decision (§7-5):** half (a) already catches a swapped weight file; the *signature* (b) only adds defense against the manifest *itself* being tampered. If the manifest is trusted (git-tracked, read-only), (a) may suffice for #598 with (b) as post-gate hardening — and then **no further TPM ceremony is needed for the gate.**
- **Dependency pinning + hash-verify:** pin / upper-bound the security-critical deps across the 6 `pyproject.toml` files.
- **Runtime egress guard + PA-mediated egress + kill-switch armed:** the import-scan egress test is green; the gate still needs the **runtime raw-socket guard**, the **egress allowlist ratified**, the **kill-switch armed** (ADR-020), AND every egress routed through the **Policy Agent** (the `DENY_EXTERNAL_NETWORK` deterministic rule needs a carve-out for PA-approved web calls). This is largely the same machinery as the W4 web-search egress proxy — it overlaps with #556.

### 2d. The test-automation lane — the force-multiplier (#619 / #621 / #622)

The production-parity boot lane (#619), the GUI harness (#621), the coverage audit (#622). This is BOTH the minimal-human-in-the-loop mandate (TEST_GOVERNANCE §2.7) AND what the #598 gate criterion requires — "independently SWAGR-verified in production posture" is only automatable with the production-parity lane.

---

## 3. The sequencing — sprints to #598

### Sprint 16 — "The Automation Wave" (heavily parallel)

Lead with the automation: it's the force-multiplier, it's the LA's mandate, and its pieces are disjoint. Dispatch **4 parallel worktree builders**:

| Builder | Work | Ticket | Working-set (disjoint) |
|---|---|---|---|
| **A** | GUI harness — extend Layer C pywinauto to the full critical-path list + add automation IDs | #621 | `tests/harness/test_winui_*`, `services/ui_winui/MainWindow.xaml(.cs)` |
| **B** | FUT-04 full weight integrity — multi-file sweep at load + `require_signed` wiring | #106 | `shared/models/weight_integrity.py`, both `gpu_inference.py::load_model()` |
| **C** | Dependency pinning + hash-verify | Tier-3 | the 6 `pyproject.toml` |
| **D** | Production-parity lane (part 1) — key-transition + sealer-stand-in tests | #619 | `tests/harness/` (owns `fakes.py`/`scenarios.py`), `shared/security` sealer/dek |

Plus the **Tier-1 reconciliation (2a)** as a fifth, light, read-mostly task. Coordination points (assign, don't race): **D owns `tests/harness/fakes.py` + `scenarios.py`; A owns the `test_winui_*` files** (the one shared-directory touchpoint); C+D both touch `pyproject.toml` but different sections (trivial). Otherwise fully disjoint.

**Outcome:** the GUI and the boot path self-verify in CI; a gate-critical item (weight integrity) lands; the suite gets the production-parity foundation that automates the #598 gate SWAGR.

### Sprint 17 — "The Boot Cluster" (serial on `launcher/__main__.py`) + egress

Three items collide on `launcher/__main__.py`; run them in the survey's recommended order (single builder, or one-at-a-time):
1. **#615 guest-boundary** — activate + verify the dormant AF_HYPERV path. *(Pending the §7-2 gate-scoping decision — may defer to land with #556.)*
2. **Tier-3 egress** — runtime raw-socket guard + the PA-mediated egress carve-out + kill-switch armed.
3. **Production-parity lane (part 2, #619)** — the production-mode **boot integration test**, written against the now-stable post-#615 / post-egress boot.

The egress work also touches `services/policy_agent/src/gpu_inference.py` (the `DeterministicPolicyChecker`); by Sprint 17 the weight-integrity work (Sprint 16, Builder B) is merged in the same file, so coordinate the two non-overlapping regions.

### Sprint 18 — "#598 GO/NO-GO" + the capstone

Production-posture SWAGR verifying **all** §5 gate criteria with `dev_mode=false` + real certs/keys — now **largely automated** by the Sprint-16 production-parity lane. The Auditor produces the gate verdict; the LA makes the **GO/NO-GO sign-off** (the irreducible governance act). Then the **#612 capstone security presentation** (produced at/after the gate, per `SECURITY_ROADMAP §9`).

---

## 4. Parallelization — the disjointness matrix (the answer to "can the fleet parallelize?")

**Execution model:** the lead orchestrator dispatches parallel **worktree builders** and **merge-gates** each (the model proven tonight: 4 builders for decrypt + substrate + routing). The autonomous fleet stays **LA-paused** (cf-program); this lead + parallel-builders shape *is* the cf-program Orchestrator + specialist-subagent pattern and is the right model for this work — no fleet re-activation needed.

```
             FUT04   Egress  Test619 WinUI   HV615   Pins
FUT04 (#106)  —
Egress (T3)  COLLIDE  —
Test619      ~        COLLIDE  —
WinUI (#621) DISJOINT DISJOINT COLLIDE  —
HV615 (#615) DISJOINT COLLIDE  COLLIDE  DISJOINT —
Pins  (T3)   DISJOINT DISJOINT COLLIDE  DISJOINT DISJOINT —
```

**Three serialization hot-spots** (assign carefully, don't race):
1. **`launcher/__main__.py`** — egress, #615, the boot test all collide → the Sprint-17 serial cluster (order: #615 → egress → boot test).
2. **`services/policy_agent/src/gpu_inference.py`** — weight-integrity (`load_model`) + egress (`DeterministicPolicyChecker`) — different methods, same file → same builder or coordinated short-lived branches (they're in different sprints here, so no live conflict).
3. **`tests/harness/fakes.py`** — the test lane (#619) and the GUI harness (#621) → the test lane owns the fixtures, the GUI harness owns the `test_winui_*` files.

**Safe-parallel set (Sprint 16):** Builders A/B/C/D run at once — weight integrity × GUI × pins × key-transition-tests are pairwise disjoint (the only touchpoints are the two coordination assignments above).

---

## 5. Automation strategy — minimal human-in-the-loop

The principle is now doctrine (TEST_GOVERNANCE §2.7): every major aspect has an automated test of its **real integrated path**. Applied to the campaign:

- **Build the automation FIRST (Sprint 16).** Once the production-parity boot lane + the GUI harness + the key-transition tests exist, the security tiers after them **self-verify in CI** — the boot lane runs the gate criteria, the GUI harness verifies the UI, the key-transition tests cover the encryption.
- **The #598 gate SWAGR becomes a CI run + a human sign-off**, not a manual boot-and-check marathon. That is the whole point of front-loading the automation.

### What still needs YOU — the irreducible-human short list
1. **The FUT-04 manifest-signing ceremony — ONLY IF you scope the signed manifest as gate-required (§7-5).** It is a 4th TPM key (`BlarAI-Manifest-Signing`, not yet provisioned). If you scope FUT-04 to hash-verify-all-weights only, **this ceremony drops and there are no new TPM ceremonies for the gate** — the three already done (DEK-seal, JWT, audit) are the whole set.
2. **Confirmation boots on real hardware** — the #615 guest-boundary boot (real Hyper-V) and the #598 boot (real TPM/certs). Production is the only "works."
3. **The gate-scoping decision** (§7-2: fidelity-2 enough, or #615 first?).
4. **The egress-policy decision** (what egress is *ever* allowed once network-facing; the kill-switch's trigger/authority — ADR-020).
5. **The #598 GO/NO-GO sign-off** — a governance act, not an automated pass.

Everything else is agent-driven + merge-gated. The arc of this plan is to make items 1–5 the *entire* surface of your involvement.

---

## 6. The horizon beyond #598 (the rest of the roadmap)

- **#556 network capabilities** — built behind glass, gated until #598:
  - **Egress side (near-term post-gate):** web-search **W4** (live `web_fetch` through the PA egress proxy) + **W5** (untrusted-web-content defenses at ingestion — ADR-013 Layer 1+2 applied to web content). The local 14B is the brain (all reasoning on-device); Kagi is the mandated privacy-respecting search provider (ADR-024). W1–W3 are already built + mocked.
  - **Ingress side (later, even-more-gated; Decision 7 deferred):** Mobile LAN Ingress (Pixel push) / authenticated listener — a separate, later decision (LAN-only vs internet-facing; the auth mechanism; biometric/Windows-Hello consent).
- **The use-case roadmap** (post-gate, by priority): **UC-002** Substrate as a standalone VM microservice (P2) → **UC-005** Code Agent (P3) → **UC-009** Autonomous Maintainer (P6, network-facing, deliberately **last**). UC-001 + UC-004 are OPERATIONAL today.
- **Re-homed / deferred:** UC-003 Cleaner (#613, separate project); ADR-022 image isolation (network-facing track); #611 live-memory mitigation / Intel Key Locker (network-facing).

---

## 7. Decisions queued for the LA (resolve at the Sprint-16 kickoff)

1. **Confirm the automation-first sequencing** (Sprint 16 = the parallel automation wave; Sprint 17 = the boot cluster). *Recommended.*
2. **Gate-scoping (2b):** is fidelity-2 sufficient for #598 with #615 as a with-#556 activation, or must #615 land before the gate? *(Changes the #598 scope.)*
3. **The egress policy** (what egress is ever allowed; the kill-switch authority) — needed before the Tier-3 egress work in Sprint 17.
4. **FUT-04 ceremony timing** — *only if §7-5 makes the signed manifest gate-required* — when to run the `BlarAI-Manifest-Signing` ceremony (in Sprint 16 to fully close #106, or land it signed-but-off and do the ceremony as a discrete step).
5. **FUT-04 scoping (§2c) — the decision that determines whether ANY ceremony remains for the gate:** does #598 require the *signed* manifest (one more TPM ceremony, `BlarAI-Manifest-Signing`), or is hash-verify-all-weights sufficient with signing as post-gate hardening (**no new ceremony**)? The three ceremonies already done (DEK-seal, JWT, audit) are the whole set unless this decision adds the manifest key.

---

## 8. Source surveys (for the new lead's audit)

- Working-set disjointness map — every remaining item's files + the collision matrix (outgoing-session survey, 2026-06-07).
- Use-Case / post-#598 horizon — the 9 UCs with status + the #556 / gated / beyond breakdown (outgoing-session survey, 2026-06-07).
- `docs/security/SECURITY_ROADMAP_air_gap_removal.md` §3–§6 (the gate criteria + the LA's ratified decisions; note its Tier-1 "remaining" list is stale — see §2a).
- `docs/DECISION_REGISTER.md` (the runtime trust/security ADR index, now maintained-by-rule).
