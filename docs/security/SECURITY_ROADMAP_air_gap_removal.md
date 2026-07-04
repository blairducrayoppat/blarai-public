# BlarAI Security Roadmap — Toward Removing the Air-Gap

**Authored 2026-06-05 by Co-Lead (overnight), against the goal Blair set:**
> *"implement the security tiers and bring BlarAI towards being secure enough to remove the air-gap."*

**Status:** campaign map + decision substrate. This document does **not** remove the
air-gap and does **not** implement the heavy tiers. It sequences the work and surfaces
the decisions only the Lead Architect can make, so the campaign can be kicked off
properly tier-by-tier. Disk-rooted: every claim cites a file, ADR, or ticket.

---

## 0. The decision this roadmap serves

The **air-gap** — zero external network dependency, fail-closed, privacy absolute —
is BlarAI's foundational security property (`CLAUDE.md` §Project Identity / §Security
Constraints). Removing it is the **single biggest threat-model shift in the project**:
today there are *zero external listeners and zero external egress paths*; afterward
there is an attack surface. That is why removing it is gated, not gradual.

- **The goal it enables (#556):** BlarAI as a home AI orchestrator / LAN control-point
  — smart-home actuation (outbound), external/mobile ingress (inbound), media
  orchestration. All of it is gated behind security hardening; none breaks the air-gap
  until the gate passes.
- **The gate (#787, GO/NO-GO):** referenced in the Sprint-12 SDV §10 but **not yet a
  ticket**. This roadmap defines its criteria (§5) and recommends creating it as the
  formal gate.
- **The prerequisite (#555):** a disk-rooted 5-domain security audit + presentation,
  *then* harden UC-001/004 to spec from the audit's findings. **Audit-first, then
  harden** — the LA-approved sequence. Sprint 12 (provenance/content-trust) was one
  slice of that hardening, executed ahead of the full audit.

**Governance posture (why this is a roadmap, not a code dump):** every heavy tier item
below hinges on a decision that is the operator's, not the builder's — key management,
VM topology, the Cleaner's precision posture, egress policy. For the one decision where
fast-but-wrong is worst, the mature path is scope → operator decision → implement with
review. Blind overnight implementation would produce security-critical code to unwind.

---

## 1. Current posture — the foundation already in place

Rooted on disk; this is what the campaign builds on, not from-scratch.

| Capability | Where | State |
|---|---|---|
| **Content-trust** — provenance model, capability-scoped action-lock, #570 AO→PA tool mediation, Stage-5 leakage redesign | ADR-023 (+ Amendment 1); `context_manager.py`, `entrypoint.py`, `pgov.py` | **DONE + live-verified** (Sprint 12) |
| **Prompt-injection defense-in-depth** — Layer 1 delimiter-neutralization + per-load datamarking, Layer 2 heuristic injection scan, Layer 3 deterministic action-lock | ADR-013; `context_manager.py` | In force |
| **Output validation (PGOV)** — 6-stage Policy-Governor output pipeline | `pgov.py` | In force |
| **Policy Agent (UC-001)** — CAR adjudication, deterministic deny rules (incl. P-004 `DENY_EXTERNAL_NETWORK`), JWT `DecisionArtifact` (5 s TTL) | `services/policy_agent/`; `shared/schemas/car.py` | Operational |
| **Trust root + isolation** — TPM-sealed signing key, de-elevation, named-pipe security descriptor, vsock host↔guest | ADR-018, ADR-019, ADR-014 | In force |
| **Manifest signing** (model weights) | FUT-04 / Tier-1 wave; `shared/models/manifest_signer.py`, `shared/security/tpm_signer.py` | Default-off, TPM-ceremony-gated |
| **Verification harness** — deterministic + real-model (Layer B) + real-UI (Layer C) | `tests/harness/` (#563) | Live; Sprint-12 coverage added (#592) |

**Honest gap:** the deterministic egress denial (P-004) exists at the PA boundary and
(since #570) at the AO tool loop — but it is **deny-known-bad**, and there are no
egress tools yet. The air-gap WAS enforced by *absence* (no network code), not by a
*tested* control. **The first egress control is now live (2026-06-05):**
`tests/security/test_no_external_egress.py` statically proves the runtime imports no
external-network library, fail-closed in the default suite — "air-gapped because a
control proves it," for the import vector. A runtime raw-`socket.connect` guard (the
address vector) and the armed kill-switch (ADR-020) remain.

---

## 2. The tier ladder (toward the #787 gate)

Per Sprint-12 SDV §10. Tiers are **roadmap milestones**, distinct from the per-tool
risk tiers (SAFE/GUARDED/DANGEROUS) of ADR-023 Amendment 1.

### Tier 1 — content-trust + foundational hardening
- **DONE:** content-trust (Sprint 12, #558 closed); manifest signing; allowlist prune; error sanitization.
- **REMAINING:** guest `dev_mode` hardening; tamper-evident audit stream; measured-boot attestation; PII-filter posture.

### Tier 2 — heavy isolation
- Full **Cleaner (UC-003)** classifier + three-field signature gate (Sprint 12 shipped only the lighter provenance tag). **(DEFERRED to post-#598 fast-follow — #613; not gate-blocking; see §6 Decision-1 amendment.)**
- **At-rest DB encryption** (sessions, substrate).
- **Run-in-VM / mTLS / per-boot certs** (today: host-mode default per `default.toml`; vsock is gateway→AO only).

### Tier 3 — supply-chain + egress
- **Dependency pinning + hash-verify.**
- **Integrity-verify ALL model weights** (today: manifest-signing exists, default-off).
- **Automated egress test** — ✅ **DONE (2026-06-05)**: `tests/security/test_no_external_egress.py` proves the runtime imports no external-network library, fail-closed in CI. (Import vector; a runtime raw-socket guard is the named follow-on.)

---

## 3. Remaining work × the decision it requires

The campaign's load-bearing column is the rightmost — these are the operator's calls.

| Item | Tier | The work | **Decision only the LA can make** |
|---|---|---|---|
| Cleaner (UC-003) | 2 | classifier + 3-field signature gate over untrusted content | **Precision/recall posture** (block-aggressive vs allow-aggressive) and the heavy-classifier memory/latency cost on the 31.3 GB ceiling |
| At-rest encryption | 2 | encrypt sessions DB + substrate | **Key management**: TPM-sealed vs passphrase; the **key-loss recovery** posture (decades-of-use implies a recovery story) |
| Run-in-VM / mTLS | 2 | move services into the Hyper-V VM; mTLS + per-boot certs | **Topology**: which services in the VM vs host-mode (today host-mode is the default *because* of GPU/FS access — reversing it has a real cost) |
| Egress policy + kill-switch | 3 | the egress allowlist + armed kill-switch | ✅ **DECIDED 2026-06-07 → ADR-027**: deny-by-default allowlist (Kagi first, grown per-feature); PA auto-approves within-list + logs all; kill-switch default-off + auto-trip on anomaly + LA-only re-arm. Build: Sprint 17. |
| Authenticated listener (#556 ingress) | post-gate | hardened inbound listener | **LAN-only vs internet-facing**; the auth mechanism; **biometric consent** (Windows Hello) for sensitive/outbound actions |
| Measured-boot attestation | 1 | attest the boot chain | ✅ **DECIDED 2026-06-07 → ADR-028**: security-material validation (manifest/keys/certs present+valid; refuse-to-start, hard-lock ×3) IS the #598 gate bar; true TPM PCR measured-boot deferred to post-gate hardening (#627). |
| PII-filter posture | 1 | PII redaction in the output path | ✅ **DECIDED 2026-06-07 → ADR-027**: screen every outbound payload, **block** on detected secrets/PII (fail-closed) at the egress boundary. Build: Sprint 17. |
| Tamper-evident audit stream | 1 | append-only, signed audit log | **Retention + the signing authority** |
| Weight integrity (all models) | 3 | verify every model's weights at load | **Turn on FUT-04 signing** via the TPM ceremony (currently default-off) |

---

## 4. The campaign sequence (multi-sprint)

1. **#555 audit + present FIRST.** The disk-rooted 5-domain audit (trust root/measured-boot · PA authorization · IPC/isolation · injection/output · privacy/network) → the LA's security decisions in §3. *Everything downstream is informed by it.* (Audit artifacts already exist at `docs/security/audit_2026-06-03/`.)
2. **Tier 1 remaining** — dev_mode hardening, tamper-evident audit stream, measured-boot, PII posture.
3. **Tier 2 (gate-critical)** — at-rest encryption, run-in-VM/mTLS. (The Cleaner (UC-003) is DEFERRED from the gate to a post-#598 fast-follow — #613.)
4. **Tier 3** — dependency pinning, weight integrity (FUT-04 on), the automated egress test.
5. **Tier verification (Sprint-18 automation sweep)** — all tiers verified against §5 in production posture; the model-loaded coverage sweep makes the §5 audit a scripted run, not a manual marathon.
6. **The #612 Capstone phase** *(its own gate-phase — LA-approved 2026-06-07)* — build the honest residual-risk presentation (the 8 must-cover points, disk-rooted) → present it to the LA in detail → the LA's **deep-dive Q&A** → **any work surfaced is tasked to an agent, resolved, and re-confirmed**. The LA's real risk-understanding pass (§5.13); a full DEC-15 phase in its own right (build → present → question → remediate), *not* the tail of Sprint 18. The sign-off does not happen until this satisfies the LA.
7. **#598 sign-off (§5.12)** — the explicit LA go/no-go, gated on step 6. The air-gap comes down here, and only here.
8. **#556 network capabilities** — built-ahead but **gated** until the sign-off passes.

Each step is a DEC-15 sprint kickoff (SDV → execution → SCR → SWAGR), not a blind build.

---

## 5. The #787 GO/NO-GO criteria (what must be true to remove the air-gap)

**§5 last verified on disk: 2026-06-07 (Stream E, Sprint 16). RECONCILED at the
Sprint-17 close (2026-06-07): the ADR-027 egress machinery (5.2 / 5.3 / 5.10) is
BUILT and shipped DORMANT — the live allowlist stays loopback + AF_HYPERV, so the
air-gap is UNCHANGED; it enforces external rules only post-#556. The offline
key-recovery path (5.5) is DONE. The FUT-04 ceremony (5.6) is the Sprint-17 batched
on-chip session (C7, PENDING green). Per-criterion S17 narrative + evidence:
`docs/sprints/sprint_17/strategic_completion_report.md` §2/§5. Every status below is
confirmed against actual code/config, not inherited from a prior doc state. Evidence
cites are file:line in the `main` worktree at that date.**

Formal gate. The air-gap comes down **only** when **all** hold:

---

### 5.1 Production-posture SWAGR verification

- [x] **DONE — verification limb (Sprint 18, 2026-06-08; independently reproduced)** —
  The production-posture verification is satisfied and **independently reproduced by the
  Sprint-18 Auditor SWAGR in `dev_mode=False`**: criterion C1
  (`tests/harness/test_model_loaded_round_trip.py`) runs the composed gateway → real AO
  over real `CERT_REQUIRED` mTLS → real Qwen3-14B → signed-manifest boot
  (`require_signed_manifest=true`, the detached `manifest.json.sig` verified) → real PGOV
  → STREAM_TOKEN, **GREEN**; C2 (model-loaded IPC-routing lock) + C4 (TUI over the real
  gateway) green; the standing gate reproduced at **2342/0**. SWAGR verdict
  **STRONG_ALIGNMENT, 0 CRITICAL / 0 MAJOR / 5 MINOR**
  (`docs/sprints/sprint_18/Strategic_Work_Analysis_and_Gap_Report_Sprint_18.md`). This is
  a `dev_mode=False` reproduction — a dev-mode "works" claim does NOT count, and this is
  not one.
  - **Two qualifications recorded (SWAGR MINOR-3 / MINOR-4):**
    **(a) C1-anchored** — the production-posture reproduction is the one composed mTLS
    path; the other tiers are verified in dev-posture + static locks, and a
    `dev_mode=False` boot-cascade tier is a forward (non-gate-blocking) strengthener.
    **(b) DONE scopes the production-posture *verification* criterion ONLY — NOT
    whole-ladder tier-completion.** The #598 air-gap decision still gates on §5.13 (#612
    capstone), §5.12 (LA sign-off), the #106 signed-manifest-runtime *remainder*
    (PARTIAL, forward track), the DORMANT egress machinery (post-#556), and #607.
    Satisfying §5.1 removes one criterion; **it does not open the gate.**
  - *Evidence of the posture flip:* `shared/security/dev_mode_guard.py::resolve_dev_mode()` — HOST mode resolves `dev_mode=False` by default (Sprint 15 EA-4b); `services/policy_agent/config/default.toml:21` `dev_mode = false`; the dev-mode interlock (`assert_dev_mode_network_facing_safe`) is wired at the PA and AO entrypoints. Sprint 18 added the production-posture *reproduction* (C1) that was the REMAINING limb.

---

### 5.2 Egress controls

- [x] **DONE (import vector)** — Automated egress test green: `tests/security/test_no_external_egress.py` statically proves the runtime imports no external-network library. Fail-closed in the default suite. *(Evidence: file present; confirmed 2026-06-07.)*
- [x] **DONE (runtime socket guard — built, armed at entry)** — `shared/security/egress_guard.py` implements the runtime raw-socket guard (AF_INET loopback + AF_HYPERV only; DNS resolution of external hostnames denied). It is armed at the REAL process entry point: `launcher/__main__.py:1131–1133` calls `egress_guard.arm()` in the `if __name__ == "__main__"` block before `main()`. The guard is written and armed on every production launch. *(Evidence: `launcher/__main__.py:1131`, `shared/security/egress_guard.py`.)*
- [x] **RATIFIED (ADR-027) + BUILT DORMANT (Sprint 17, C3/H-a)** — Egress allowlist policy ratified (ADR-027); the allowlist-widening *mechanism* (`egress_guard.allow_external_endpoint`, deny-by-default, one vetted endpoint at a time) is built. **The live list is NOT widened** — it stays loopback + AF_HYPERV, so the air-gap is unchanged; the mechanism enforces external rules only once a web feature ships post-#556. *(Evidence: `shared/security/egress_guard.py`; `tests/security/test_egress_core.py`; Sprint-17 merge `7034f9a`.)*
- [x] **BUILT DORMANT (Sprint 17, C3/H-a)** — ADR-020 network-facing kill-switch: `egress_guard.trip(reason)` cuts ALL egress (latched) + alerts; auto-trips on an off-allowlist attempt or an exfil-screen detection; LA-only `rearm()`; default-off. Wired live at `arm()` (every boot) but inert until an external endpoint is allowlisted (post-#556). *(Evidence: `shared/security/egress_guard.py`; `tests/security/test_egress_core.py`.)*

---

### 5.3 Every egress through the Policy Agent

- [x] **BUILT DORMANT (Sprint 17, C3/H-b)** — Every egress flows through the **Policy Agent** (deterministic rule `DENY_EXTERNAL_NETWORK`, enforced at BOTH the PA boundary and the AO tool loop — it lives in `gpu_inference.py::DeterministicPolicyChecker` RULE 3). The ADR-027 §2 carve-out is built: an allowlisted host (http/https only) is auto-approved + logged. **DORMANT** — `_EGRESS_ALLOWLIST` is empty by default, so every external URL is still denied (byte-for-byte as today); the outbound payload is also screened by `exfil_screen` (block-on-detect) before send once active. Full SWAGR-verification in the production posture is the Sprint-18 sweep. *(Evidence: `services/policy_agent/src/gpu_inference.py`; `shared/security/exfil_screen.py`; `tests/security/test_egress_screen.py`; merge `010bda6`.)*

---

### 5.4 Inbound listener

- [x] **DONE (by deliberate decision — Decision 7)** — Inbound listener: NONE. Decision 7 (2026-06-05, §6) deferred all external listeners to a later, even-more-gated decision. Zero remote attack surface is added at the air-gap-removal gate. The criterion is satisfied by absence. *(Evidence: §6 Decision-7 in this file.)*

---

### 5.5 At-rest encryption

- [x] **DONE** — At-rest encryption on for the session store (AES-256-GCM `EncryptedSessionStore`, TPM-sealed DEK). Fail-closed refuse-to-start in production if the DEK cannot be unsealed — no plaintext fallback path. *(Evidence: `launcher/__main__.py:878–918` Step 5 comment + `build_session_store()` call; `services/ui_gateway/src/session_store.py`; `shared/security/field_cipher.py` + `dek_envelope.py`; `shared/security/provision_dek_keystore.py`.)*
- [x] **DONE** — AO substrate encrypted (field-level AES-256-GCM). *(Evidence: `services/assistant_orchestrator/src/substrate.py`.)*
- [x] **DONE** — TPM key `BlarAI-DEKSeal` provisioned on-chip (EA-4 ceremony, Sprint 15). *(Evidence: `shared/security/ceremony_preflight.py:39` constant; preflight check #3 probes it; confirmed provisioned per FORWARD_EXECUTION_PLAN §2a.)*
- [x] **DONE (Sprint 17, C6)** — Tested key-recovery path: the DEK envelope carries a second wrap under an offline recovery key (Decision 2), and `tests/security/test_key_recovery.py` proves a FRESH environment with no usable TPM (dead-chip / hardware-migration stand-ins) decrypts real at-rest data via the offline recovery key, with wrong-key / all-zero / tampered-wrap / foreign-ciphertext refusals. Gate tier green (SoftwareSealer stand-in). A real-TPM recovery round-trip (recover a TpmSealer-sealed keystore on a chip where the seal key was deleted) is an on-chip nicety, not gate-blocking (the recovery path never touches the sealer). *(Evidence: `shared/security/recovery_key_store.py`, `shared/security/dek_envelope.py::unseal_via_recovery_hex`, `tests/security/test_key_recovery.py`; Sprint-17 merge `873f5b5`.)*

---

### 5.6 Model weights integrity (FUT-04)

- [x] **GATE-MET via boot-enforcement (Sprint-17 C7, 2026-06-07); #106 stays OPEN as PARTIAL for forward scope.** Weight-integrity history (Sprint 16 Builder B), Sprint-16-start state below — superseded by the Sprint-17 close update:
  - **➤ Sprint-17 CLOSE (2026-06-07, C7 GREEN):** the `BlarAI-Manifest-Signing` ceremony RAN — 4th TPM key provisioned (trust anchor `508defe5…`), `require_signed_manifest = true` flipped LIVE in both service configs, signature verified under enforcement, standing gate **2342/0** (the flip un-skipped 2 signed-manifest tests), the real production boot cleared the manifest gate. **The §5.6 / D-1 gate requirement (signed manifest gate-required for #598) is MET.** #106/FUT-04 remains OPEN as **PARTIAL** for forward scope — runtime per-adjudication re-verification + copy-on-write (read-only mmap) — which is **NOT a #598 blocker** (ADR-028: boot-time security-material validation is the gate bar). Perf note: a full per-adjudication re-hash of the 14B weights won't fit the ticket's 500 ms budget; the remainder needs a sampled / mmap-page-fault design. *(Evidence: ledger `20260607_224258_sprint17-onchip-close.md`; SCR §9; #106 c.928.)*
  - **DONE:** `verify_weight_integrity` exists in `shared/models/weight_integrity.py`; the PA and AO `gpu_inference.py::load_model()` call it (for the primary `.bin` only as of Sprint-16 start).
  - **DONE:** `manifest_signer.py` and `provision_manifest_signing_key.py` both exist and are wired. The manifest-signing *mechanism* is present. Default config ships `require_signed_manifest = false` (`services/policy_agent/config/default.toml:26`).
  - **REMAINING (Sprint 16 B):** extend the weight-integrity sweep to **all** entries in the manifest (not just the primary `.bin`).
  - **REMAINING (ceremony — Sprint 17 on-chip session, C7, PENDING green):** run the `BlarAI-Manifest-Signing` TPM ceremony (4th key, runbook `docs/runbooks/manifest_signing_ceremony.md`), flip `require_signed_manifest = true`, and verify a clean production boot. The all-entries weight-integrity sweep was DONE in Sprint 16 B; the ceremony + flip + boot are the Sprint-17 batched on-chip session (committed ≠ done until green). The TPM key `BlarAI-Manifest-Signing` is **NOT YET PROVISIONED** (canonical name `shared/models/manifest_signer.py:44`; provisioning script `shared/security/provision_manifest_signing_key.py`). #106/FUT-04 stays PARTIAL until C7 is green.
  - **Gate requirement (Decision D-1, Sprint-16 SDV):** the **signed** manifest IS gate-required for #598 — not hash-verify-only. So this criterion is PARTIAL until the ceremony runs and `require_signed = true` is active.
  - *(Evidence: `shared/models/manifest_signer.py:44` `MANIFEST_SIGNING_KEY_NAME = "BlarAI-Manifest-Signing"`; `shared/security/ceremony_preflight.py` checks `_DEK_SEAL_KEY`, `_AUDIT_KEY`, `_JWT_KEY` only — no manifest key; `services/policy_agent/config/default.toml:26` `require_signed_manifest = false`.)*

---

### 5.7 Tamper-evident audit stream

- [x] **DONE** — Hash-chained TPM-signed audit stream live. `shared/security/audit_log.py` implements an append-only, cryptographically-chained adjudication audit log: each record SHA-256-hashes its canonical fields chained to the prior record; TPM ECDSA P-256 signs each record via `TpmRecordSigner` using the dedicated `BlarAI-Audit-Signing-Key-v1` key (separation of duties from the PA JWT key). `AuditProvisioningError` is raised at startup in production when the TPM audit key is unprovisioned — refuse-to-start (ADR-025 §2.8(a)). *(Evidence: `shared/security/audit_log.py:1–66`, `audit_log.py:158–220`; Sprint 13 Domain 7 / Sprint 14 TPM swap #605.)*
- [x] **DONE** — TPM key `BlarAI-Audit-Signing-Key-v1` provisioned on-chip (EA-4 ceremony, Sprint 15). *(Evidence: `shared/security/ceremony_preflight.py:40` constant; preflight check #4 probes it; confirmed provisioned per FORWARD_EXECUTION_PLAN §2a.)*
- [x] **DONE (ADR-029, #607)** — Retention policy: **"segmented keep-everything with a bounded working set"** (rotate-and-retain). The full forensic history is kept forever in sealed, individually-verifiable, gzip-compressed segments rotated at a size/count cap (default 64 MiB / 100k records, whichever trips first), so the active file + the in-RAM working set stay bounded — closing the prior unbounded-RAM + O(n)-boot gap. Sealed segments are anchored by a signed `audit-segments.jsonl` index, so tamper-evidence spans files; `verify(full=True)` walks every sealed `.jsonl.gz` end-to-end. A retention ceiling (`audit_archive_max_bytes` / `audit_archive_max_age_days`) defaults **OFF** (keep all); if ever set, WHOLE sealed segments are pruned oldest-first and **each prune is itself audited** (a signed `RETENTION_PRUNE` record), so a policy gap is distinct from a #606 tail-deletion. *(Evidence: `shared/security/audit_log.py` segmentation + `verify(full=…)`; wired at `services/policy_agent/src/entrypoint.py::_build_audit_log`; `services/policy_agent/config/default.toml` `[security]` knobs; `shared/tests/test_audit_log.py` Groups K–P. Rejected alternatives — time-purge / FIFO hard-drop / status-quo unbounded — in ADR-029.)*

---

### 5.8 Measured-boot ordering

- [x] **DONE** — Launcher enforces strict boot ordering: (1) admin check → (1.5) per-boot mTLS cert provisioning → (2) Hyper-V VM → (2.5) shared LLMPipeline → (3) PA measured-boot gate → (4) AO entrypoint → (5) session store (encrypted) → (6) transport gateway → (6a) handshake preflight → (6b) prompt-flow preflight. Services cannot start out of order. *(Evidence: `launcher/__main__.py` Steps 1–6b, lines ~591–1119.)*
- [x] **DONE** — PA `run_measured_boot()` enforces phase ordering within the PA boot: attestation (security-material validation) → weight integrity → model load → rules load → listener start. Any step failure is fatal; `hard_locked` after max attempts (3). *(Evidence: `services/policy_agent/src/boot.py:84–159`; `services/policy_agent/src/entrypoint.py:419–476`.)*

---

### 5.9 Measured-boot attestation policy (DECIDED 2026-06-07 → ADR-028)

- [x] **DECIDED (ADR-028, 2026-06-07)** — The term "attestation" in the PA's `MeasuredBootStep` named `attestation_gate` covers **security-material validation** (manifest present + digest valid + JWT TPM key provisioned + CA cert present), not TPM PCR (Platform Configuration Register) remote attestation. The comment in `boot.py:9` says "Verify TPM/Pluton attestation (or dev-mode skip)" but the implementation (`_phase_attestation` in `entrypoint.py` → `_validate_security_material`) validates the key/manifest material only — it does **not** read PCR values or produce a remotely-verifiable attestation quote. The `dev_mode` parameter to `run_measured_boot` is explicitly unused (`_ = dev_mode` at `boot.py:102`). The *action* on failure is clearly defined (refuse-to-start, hard-lock after 3 attempts — `entrypoint.py:467–476`); the *scope* of what "attestation" covers is the open question for the gate. *(Evidence: `services/policy_agent/src/boot.py:9,102`; `services/policy_agent/src/entrypoint.py:282–310`; no PCR read anywhere in the measured-boot path.)* **Decision (ADR-028):** for the #598 gate this security-material validation IS the attestation bar — it fail-closes on forged/missing trust material (the network-relevant vector). True TPM PCR measured-boot (firmware/bootloader/OS boot-chain integrity — a *physical*-tamper control orthogonal to air-gap removal, carrying re-baseline-on-every-firmware/OS-update friction) is a deliberately-designed **post-gate** hardening item (#627), not a #598 blocker.

---

### 5.10 PII-filter posture (DECIDED 2026-06-07 → ADR-027; build Sprint 17)

- [~] **DECIDED (ADR-027, 2026-06-07): block-on-detection at the egress boundary; build Sprint 17** — PII (Personally Identifiable Information) redaction posture at the egress boundary. Decision 5 (§6): "off locally, redact at the egress boundary." The PGOV pipeline has a `pii_mode` config field; AO `default.toml:47` ships `pii_mode = "off"`. The detector (Luhn-less card check accuracy issue flagged in Decision 5) and the precise redact-vs-block policy at the egress path are both open items that activate when the network-facing work lands. The posture decision is ratified in principle (§6 Decision-5); the *implementation at the egress boundary* is REMAINING. *(Evidence: `services/assistant_orchestrator/config/default.toml:47` `pii_mode = "off"`; `tests/security/test_secure_defaults.py:13` notes `pii_mode` is a Tier-1 decision the roadmap leaves to the LA.)*

---

### 5.11 Dev-mode interlock

- [x] **DONE** — The dev-mode / network-facing interlock is live. `shared/security/dev_mode_guard.py::assert_dev_mode_network_facing_safe()` fails closed (raises `DevModeNetworkFacingError`) when both `dev_mode=True` and `network_facing=True` are active. Deny-by-default: `None` is treated as the unsafe value for both inputs. Production is now the default (`dev_mode=False` for HOST, Sprint 15 EA-4b). *(Evidence: `shared/security/dev_mode_guard.py:121–161`.)*

---

### 5.12 Explicit LA sign-off

- [ ] **REMAINING** — Explicit LA sign-off — a governance act, not an automated pass. Required when all other criteria are met **AND §5.13 (the #612 capstone + the LA's deep-dive) is satisfied** — the sign-off is the LA's *informed* go/no-go after a real risk-understanding pass, not a rubber-stamp at the end of an automation run.

---

### 5.13 Capstone security presentation + LA deep-dive (#612) — the sign-off precondition

- [ ] **REMAINING (LA-directed 2026-06-07)** — Before the §5.12 sign-off, the LA takes his **real deep-dive into the security picture and the residual risks of removing the air-gap, even after all the hardening done**: the **#612** capstone presentation (the honest AFTER-posture + residual-risk register — see the #612 ticket's 8 must-cover requirements; the heart for this purpose is the gaps/mitigation register + the data-flow / hostile-page / future-web-fetch scenarios) is delivered, the LA goes through it **in detail and asks questions**, and **any work that surfaces during the presentation/Q&A is tasked to an agent and resolved** — all *before* sign-off. Sequence: tiers verified (§5.1–§5.11, production posture) → **capstone + deep-dive (§5.13)** → sign-off (§5.12). #612 is a closing deliverable produced once the posture is final (all tiers built + verified), but it is delivered **before** the sign-off — it makes the sign-off informed, not a victory lap. *(This supersedes the #612 ticket body's "WHEN: at/after the #598 gate" — see the ticket's 2026-06-07 amendment comment.)*

---

### TPM key state (verified on disk, 2026-06-07)

The following table records what `ceremony_preflight.py` probes (disk evidence) vs.
what the FORWARD_EXECUTION_PLAN §2a confirmed. Chip-state cannot be verified from
disk — this is what the on-disk provisioning scripts and the preflight constants
confirm. The actual TPM NV-index probe requires running the preflight on the chip.

**Update 2026-06-09 (chip-verified — supersedes the disk-inference caveats below):**
the on-chip probe has now been run. `shared/security/verify_trust_root.py` proved
**all four** trust-root keys **resident + functional + non-exportable** on the real
STMicroelectronics TPM 2.0 — each private-key-export refusal proven *directly per
production key* (not by equivalence). All four are now **VERIFIED-LIVE**. Artifact:
`docs/security/trust_root_verification_2026-06-09.json` (#635); follow-ups #636.

| Key name | Purpose | Disk evidence | Provisioned state |
|---|---|---|---|
| `BlarAI-DEKSeal` | Seals the at-rest Data Encryption Key (DEK) via RSA-2048 OAEP | `ceremony_preflight.py:39` constant; `provision_dek_keystore.py` ceremony | **PROVISIONED** (EA-4 ceremony, Sprint 15; confirmed FORWARD §2a) |
| `BlarAI-PA-JWT-Signing` | ECDSA P-256 — signs PA `DecisionArtifact` JWTs (5 s TTL) | `ceremony_preflight.py:41` constant; `provision_signing_key.py` ceremony | **PROVISIONED** (EA-4 ceremony, Sprint 15; confirmed FORWARD §2a) |
| `BlarAI-Audit-Signing-Key-v1` | ECDSA P-256 — signs each hash-chained audit record (separation of duties from JWT key) | `ceremony_preflight.py:40` constant; `audit_log.py:65` `AUDIT_TPM_KEY_NAME`; `tpm_signer.ensure_key()` idempotent at first sign | **PROVISIONED** (EA-4 ceremony, Sprint 15; confirmed FORWARD §2a) |
| `BlarAI-Manifest-Signing` | ECDSA P-256 — signs the weight-integrity manifest (FUT-04 / ADR-018) | `shared/models/manifest_signer.py:44` constant; `provision_manifest_signing_key.py` ceremony script exists but is **NOT in `ceremony_preflight.py` key checks** | **PROVISIONED + VERIFIED-LIVE** (on-chip 2026-06-09) — `ceremony_preflight.py` probes it (9/9 READY) and `verify_trust_root.py` proved it resident + functional + non-exportable; `require_signed_manifest=true` since Sprint 18 |

*Disk-only caveat:* PROVISIONED status is inferred from (a) the ceremony scripts being
present and having been run (per FORWARD §2a on-disk confirmation), and (b) the
preflight's `key_exists()` probe design. Neither this audit nor any non-chip agent can
confirm the TPM NV-index contains the key without running `ceremony_preflight.py` on
the actual machine.

---

### Summary: §5 gate-criterion status (2026-06-07; amended 2026-06-09)

| Criterion | Status | Sprint home |
|---|---|---|
| Production-posture SWAGR (verification limb) | **DONE (S18, 2026-06-08)** — C1 production-posture round-trip reproduced by the independent SWAGR (`dev_mode=False`, real mTLS + signed-manifest boot, STRONG_ALIGNMENT); gate reproduced 2342/0. **Scopes the verification criterion only — NOT whole-ladder completion** (#598 still gates on #612 / §5.12 / #106-remainder / egress) | Sprint 18 |
| Egress import-scan test | DONE | Sprint 12 / in force |
| Runtime egress guard built + armed | DONE | Sprint 15 / in force |
| Egress allowlist mechanism | **RATIFIED (ADR-027) + BUILT DORMANT (S17, C3)** — live list NOT widened (air-gap unchanged) | Sprint 17 / dormant until post-#556 |
| Kill-switch (ADR-020 network-facing) | **BUILT DORMANT (S17, C3)** — trip()/rearm(), default-off | Sprint 17 / dormant until post-#556 |
| Every egress through PA (network tools) | **BUILT DORMANT (S17, C3/H-b)** — carve-out + exfil screen, **WIRED-dormant via #634 (2026-06-09, `651ef4a`)**: registers at arm-time, **destination-scoped** (external-allowlisted sockets only — never internal loopback/vsock); `_EGRESS_ALLOWLIST` empty ⇒ no-op today | Sprint 17 + #634 / dormant until post-#556 |
| Inbound listener | DONE (none — Decision 7) | N/A |
| At-rest encryption — sessions + substrate | DONE | Sprint 14 |
| At-rest encryption — offline key-recovery path | **DONE (S17, C6)** — fresh-environment recovery lock green | Sprint 17 |
| Weight integrity — all-entries sweep | DONE | Sprint 16 B |
| Weight integrity — signed manifest active | REMAINING (ceremony) — **S17 on-chip session (C7), PENDING green** | Sprint 17 on-chip |
| Tamper-evident audit stream | DONE | Sprint 13/14 |
| Audit retention policy | **DONE (ADR-029)** — "segmented keep-everything with a bounded working set" (#607); rotate-and-retain, sealed signed segments, prune-is-audited | DONE |
| Measured-boot ordering (launcher + PA) | DONE | Sprint 15 |
| Measured-boot attestation policy (PCR scope) | **DECIDED (ADR-028 + Am.1)** — material-validation IS the bar; true PCR measured-boot → #627 post-gate; **Am.1 (2026-06-10): production keys will NOT be PCR-bound** (key-sealing variant decided-against, PoC-informed; #627 attestation-*check* unchanged) | DECIDED |
| PII-filter posture at egress boundary | DECIDED (ADR-027: block) + **BUILT DORMANT (S17, exfil_screen)** | Sprint 17 / dormant until post-#556 |
| Dev-mode interlock | DONE | Sprint 15 |
| **Capability-token containment (#638)** | **DONE (2026-06-09)** — 5s TTL + nonce-TTL alignment (replay window closed) + epoch `revoke()` caller; merged `9ecea5a`, gate-green. *LA-added gate criterion 2026-06-09 (via #612 deep-dive).* | guide-orchestrated build |
| **ESCALATE human-review consumer (#639)** | **DONE (2026-06-09/10)** — consumer built+wired+merged (`494ebb8`) + **ACTIVATED** (TUI modal live-verified, verifier=tui) + **Windows-Hello biometric verifier (#649) merged `c1f51e9` + LA fingerprint live-verified 2026-06-10** (3 real fingerprint APPROVEDs + 3 cancel DENIEDs exit-15, verifier=hello; fail-closed exit-code contract; C# UserConsentVerifier helper — same Windows-SDK projection the WinUI already targets, no new dependency). **Hello = the production verifier on BOTH surfaces when available** (system dialog, surface-independent); TUI modal = fallback. **Dormant-in-practice** until an escalating tool ships (the 4 current tools build no escalatable CAR). *LA-added gate criterion 2026-06-09.* | guide build + LA live-verify (modal + fingerprint) |
| **Named-pipe peer/PID check (#640)** | **SUSPENDED from gate (2026-06-09)** — the LA suspended this as a gate requirement pending further consideration. Pipe still authenticates by OS perms only (no peer check) — remains an open hardening item, just no longer gate-blocking. *Added then suspended by LA 2026-06-09 (via #612 deep-dive).* | deferred (not gating) |
| **Data-map ACL/integrity hardening (#637)** | **DONE (2026-06-09)** — merged `2d82f69`: item 1 owner-preserving DACL lock-down built (sessions.db, substrate.db, DEK keystore, audit log, `certs\`) + items 2 & 4 cleanups + items 3 & 5 trust boundaries documented (DATA_MAP §7). NO live-verify per LA decision. *LA-added gate criterion 2026-06-09; the ticket itself frames these as defense-in-depth atop at-rest encryption ("not gate-blocking, ACCEPTED-RESIDUAL"), elevated by LA decision.* | guide build (LA chose: do 2&4, document 3&5, build 1, no live-verify) |
| Capstone + LA deep-dive (#612, §5.13) | REMAINING (gate-phase 6, pre-sign-off) | Sprint 18 |
| Explicit LA sign-off (§5.12) | REMAINING | Sprint 18 (phase 7) |

**Counts (post-Sprint-18 close):** DONE: 11 (+ §5.1 production-posture *verification* limb — S18 C1 reproduced by the independent SWAGR in `dev_mode=False`, STRONG_ALIGNMENT) · DECIDED: 1 (5.9 attestation scope → ADR-028) · BUILT-DORMANT: 4 (egress allowlist / kill-switch / PA carve-out / PII screen — enforce only post-#556) · REMAINING: audit retention (#607), the #612 Capstone phase (§5.13), and the §5.12 LA sign-off. (The signed-manifest ceremony is C7-enforcement-live — S18 C1 verified the detached `manifest.json.sig` at boot; #106's runtime per-adjudication re-verification *remainder* is on the forward track.) **§5.1 DONE scopes the verification criterion only** — the air-gap stays UP; **#598** (the roadmap's conceptual "#787") remains the GO/NO-GO, gated behind the #612 Capstone phase + the §5.12 sign-off.

**LA-added gate criteria (2026-06-09, via the #612 deep-dive — updated post-decisions):** four hardening items were elevated from deferrable residuals to **gate-blocking**; after the deep-dive the LA settled them as follows — **#638** capability-token containment (**DONE**, `9ecea5a`); **#639** ESCALATE human-review consumer (REMAINING — LA chose an inline operator confirmation, goal Windows-Hello fingerprint); **#640** named-pipe peer/PID check (**SUSPENDED 2026-06-09** — the LA pulled it back from the gate to reconsider; still an open hardening item, no longer gate-blocking); **#637** DATA_MAP §7 ACL/integrity hardening (REMAINING — LA chose: action items 2 & 4, document 3 & 5, build item 1 owner-preserving). The egress-screen prerequisite **#634** (exfil-screen wiring) was **MERGED 2026-06-09 (`651ef4a`, gate-green 2372/2)** — destination-scoped + dormant. Net (post merge-gate, 2026-06-09): **all LA-added PA/containment items are built+merged** — **#638** token containment (`9ecea5a`), **#634** exfil-screen wiring (`651ef4a`), **#643** egress proving (`14d21c3`), **#637** data-map hardening (`2d82f69`) all DONE; **#639** ESCALATE consumer **DONE** (`494ebb8` + TUI activation, **mechanism live-verified** 2026-06-09; **the Windows-Hello biometric goal landed as #649** — merged `c1f51e9` 2026-06-10, **LA fingerprint live-verified**, Hello = the production verifier on both surfaces, TUI modal = fallback — dormant-in-practice until an escalating tool ships); **#640** suspended. The egress (#634/#643) stays **DORMANT** until deliberately activated post-#556; the #639/#649 consumer is **ACTIVE** (registered at launch) but has no producer yet. #598 now waits on the #612 capstone phase, the §5.12 sign-off, and #607. (Standing gate baseline: see `docs/TEST_GOVERNANCE.md` §1 — bumped 2026-06-10 post-#649.)

---

## 6. Decisions — RATIFIED by the LA (2026-06-05)

Walked through one at a time with the LA. These are now binding inputs to the campaign (gate ticket: **Vikunja #598** — the roadmap's conceptual "#787").

1. **Air-gap bar: FULL (Tier 0+1+2+3).** Nothing comes down until all four tiers are complete + verified. **Supersedes** the audit's "Tier 0+1 minimum" — the LA requires the full posture (incl. at-rest encryption, VM containment; the Cleaner DEFERRED from the gate to a post-#598 fast-follow per the 2026-06-05 LA amendment — #613) before going online.
2. **At-rest encryption: TPM-sealed key + offline recovery key.** Strong daily binding (a stolen disk/backup is noise) PLUS a one-time offline recovery key so a dead chip / hardware migration doesn't lose the decades-lifespan data. *Rejected:* TPM-only (chip-welded → lost on hardware change); passphrase-only (boot friction + forget-risk).
3. **VM topology: HYBRID.** Network-facing code runs in the Hyper-V VM (hostile web content contained); the GPU-bound AO + 14B stay on the host; sanitized data crosses via vsock. Sidesteps the unproven Lunar Lake GPU-passthrough. *Rejected:* full-VM (passthrough risk); host-only (no containment — excluded by the full bar).
4. **The Cleaner (UC-003): data-normalizer first, Layer-1 sanitizer second.** Primary purpose = noise-stripping for knowledge-store *quality* (anti-"inference pollution"); security sanitization is Layer 1 of 3 (backstopped by spotlighting + the action-lock), so it need not be paranoid. Scope: local files + web-fetched content (mobile ingress deferred with #7). Quarantine: **tunable, start conservative**. *(Co-Lead had mis-framed this security-first; corrected against the use-case text at the LA's prompt.)* **Amendment (2026-06-05):** the Cleaner is DEFERRED from the critical path / #598 gate to a post-gate fast-follow (#613) — it is primarily a data-quality feature, and the catastrophic-outcome injection/exfil defenses (action-lock + provenance + PA egress mediation + exfil-screen) do not depend on it. Still tracked; not cancelled. **Amendment (2026-06-06):** the LA removed the Cleaner from THIS roadmap *entirely* — no longer a post-#598 fast-follow within the air-gap campaign, but re-homed to a separate/future project (#613, superseding the 2026-06-05 deferral). The deterministic injection/exfil backstops remain the gate-verified defense, unaffected. *(Remaining inline refs in §1/§3/§4 + Decision-1 still read "post-#598 fast-follow" — doc-hygiene reconciliation tracked under #613.)*
5. **PII in output: off locally, redact at the egress boundary.** User sees their own data in their own replies (no friction); secrets are detected + redacted/blocked only when output heads toward a tool/network/egress path. Activates with the network features; the detector's accuracy (the Luhn-less card check) must be fixed first.
6. **Egress: per-action, Policy-Agent-mediated + exfil-screened**, on a fail-closed baseline — the air-gap becomes a guarded door. Handles web-nav's arbitrary destinations (adjudicate the *action* + screen the outbound, not allowlist the web). *Rejected:* tight-allowlist-only (can't handle the web); category-allowlist (too loose).
7. **Ingress: NONE now — deferred.** Zero external listeners in this campaign; the air-gap removal is **egress-only**. The Mobile LAN Ingress (Pixel push) and any internet-facing listener are deferred to a separate, later, even-more-gated decision. (Smallest attack surface — no remote attack surface added at all.)

8. **dev-mode posture: production-by-default + explicit-loud-opt-in + network-facing interlock.** dev-mode (security-off: no mTLS, throwaway keys, no measured-boot) is a dev convenience — run without the full TPM-key + per-boot-cert ceremony. Today it's the *silent running default*: the launcher forces `dev_mode_override=True` for HOST (`launcher/__main__.py:584,650`) and `guest_runtime.toml` ships `dev_mode=true`. This is the audit's "worst default" — but the LA named a consequence worse than the security one: with dev-mode the silent default, **every test and every "BlarAI works" report validated the dev-mode posture, not the shipping one** — green on a configuration that would never ship, so agents repeatedly reported the system working when the production posture did not. A config-level mock-passes-prod-fails trap. Ratified fix: (a) launcher stops forcing dev-mode; (b) shipped configs secure (`dev_mode=false`) — running-default flip gated on the Tier-2 cert/mTLS build; (c) dev-mode becomes an explicit, LOUD, local-dev-only flag (never silent, never a shipped `dev_mode=true` profile); (d) **interlock** — the *production* posture (real data/keys, no explicit flag) can never silently/accidentally go network-facing in dev-mode (fail-closed refuse). **Web-nav stays testable in dev-mode** via the explicit loud opt-in against test data + throwaway keys (a sandbox), not the real substrate/key — what's blocked is *silent/default* insecure, not deliberate testing. The **guest-profile stays** (needed for the hybrid VM) but is rebuilt *hardened*, not kept as a `dev_mode=true` placeholder. *(Surfaced by the LA's "why does the guest-profile exist / how would we test web-nav / dev-mode-default got us in trouble before" challenges.)*

**Net campaign shape:** reach OUT under tight, adjudicated control (web-nav egress); let NOTHING in; encrypt everything at rest; contain hostile web content in the VM; clean what enters memory. The air-gap comes down only when §5's criteria hold AND the LA signs off (#598).

---

## 7. What was NOT done overnight, and why

Per the goal, real progress was made on the *safe* edges — #592 (verification harness
for Sprint-12) and #593 (DANGEROUS fail-closed, closing the SWAGR fail-open). The
heavy Tier-2/3 features were **deliberately not blind-implemented**: each hinges on a
§3 decision, and removing the air-gap is the one place where unreviewed speed is the
worst outcome. This roadmap is the fastest **safe** path — the campaign is ready to
execute the moment the §6 decisions are made.

---

## 8. Deferred threat vectors (acknowledged, not denied)

Threats that are real but deliberately **out of scope for initial development** — recorded here so they
are tracked, not dismissed, and revisited when the threat model extends (post-network-facing, #556).

### 8.1 Live-memory attacker (DEK + decrypted data in RAM)

At-rest encryption (Tier-2, Sprint 14 / ADR-025) protects data **on disk** — a stolen disk or a leaked
backup yields pure ciphertext. It does **not** protect data **in memory while BlarAI is running**: the
Data-Encryption Key (DEK), decrypted fields, and the decrypted embedding search-matrix necessarily live
in RAM during operation. An attacker with **code-execution on the live machine**, or one performing a
**cold-boot RAM extraction**, could read them.

- **Why deferred (not denied):** while air-gapped there is no remote attack surface to gain that
  code-execution, and physical cold-boot access is a different threat class (and a different mitigation
  set) from the at-rest / stolen-disk model Tier-2 defends. It is genuinely out of scope for the
  at-rest control — by design, not by oversight.
- **When revisited:** when the campaign goes network-facing (#556) and a remote code-execution path
  becomes conceivable, the live-memory vector graduates from acknowledged to actively-mitigated.
- **Candidate mitigations to evaluate then:** **Intel Key Locker** (AES keys held as CPU-internal,
  non-extractable handles — available on the Lunar Lake class hardware); **minimized key residency**
  (zeroize keys and decrypted fields immediately after use; unload the embedding-cache when idle rather
  than holding it for the whole session); and OS-level memory protections (locking pages against swap,
  guarded heap regions).
- **Tracking:** Vikunja **#611**.

*(Logged at the ADR-025 design gate, 2026-06-05, on LA direction: the live-memory vector is deferred,
not denied. ADR-025 §3 "Limits" points here.)*

---

## 9. Capstone deliverable — the post-hardening security presentation (#612)

The campaign closes with a comprehensive security-posture presentation for the LA — the closing
bookend to the 2026-06-03 audit deck (§1 / `docs/security/audit_2026-06-03/`). Where the audit showed
the BEFORE ("safe by environment, not yet by construction") and what had to change, this shows the
AFTER: the full hardened posture, disk-rooted (every claim cites real code / ADR / ticket). Produced
at/after the #598 gate (all tiers built + verified). Load-bearing for the IAPP AIGP (AI Governance
Professional) portfolio (the documented journey IS the portfolio) and for the LA's own operational
mastery of the system.

It must cover, in plain language an intelligent non-specialist can follow and re-explain:

1. **Every security layer** — the full stack, end to end (air-gap; TPM trust root + sealed keys;
   at-rest encryption; the Policy-Agent authorization choke-point; prompt-injection defense-in-depth;
   PGOV output validation; the Cleaner; VM/mTLS containment; the tamper-evident audit stream; egress
   controls + kill-switch; the dev-mode interlock; measured-boot).
2. **How the layers interact** — the architecture: component + trust-boundary diagrams (the audit
   deck's diagram style, updated to the hardened state).
3. **The residual gaps**, each with its tracking ticket and status (e.g. live-memory #611,
   audit tail-deletion #606, retention #607, embedded-PAN PII #608) — what is covered vs.
   deferred-and-tracked, and why each deferral is acceptable.
4. **Data flows through representative agent task scenarios** — end-to-end walkthroughs showing the
   data and the control at each hop.
5. **The security gates / fail-closed choke points.**
6. **The critical load-bearing elements** that must never be weakened.
7. **The user-operator mistakes to avoid** (the footgun list — e.g. losing/exposing the offline
   recovery key, running the production posture network-facing in dev-mode, rushing the ceremony).

Format: the audit-deck shape (diagram-rich HTML) or the LA's choice at production time. The full
requirement set — including the accessibility bar (deep enough for the LA, explainable to a
non-specialist) and the source material (BUILD_JOURNAL, ADRs, SCRs/SWAGRs, the audit deck) — lives on
the tracking ticket. **Tracked: #612.** Produced at/after #598 (NOT now — the posture isn't final
yet); this section captures the intent so the eventual deliverable is built to it.

---

**References:** `CLAUDE.md`; ADR-023 (+ Amendment 1); ADR-013, ADR-014, ADR-018, ADR-019, ADR-020, ADR-025; Sprint-12 SDV §10 + SCR; `Use Cases_FINAL.md` (UC-001/003/004); Vikunja #555 (audit+harden), #556 (network-facing), #558 (closed), #559 (Cleaner/Tier-2), #570/#590/#591/#593 (content-trust), #598 (GO/NO-GO), #611 (live-memory vector), #612 (capstone security presentation), #613 (Cleaner deferral); `docs/security/audit_2026-06-03/`.
