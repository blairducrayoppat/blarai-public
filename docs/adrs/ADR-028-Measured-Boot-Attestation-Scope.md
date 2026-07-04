# ADR-028 — Measured-Boot Attestation Scope for the #598 Gate

**Status:** ACCEPTED 2026-06-07 (Lead-Architect-decided via guided walkthrough).
**Deciders:** Lead Architect (blarai); Orchestrator (facilitation).
**Builds on:** ADR-018 (TPM 2.0 trust root). **Relates to:** #598 (air-gap GO/NO-GO gate),
`SECURITY_ROADMAP_air_gap_removal.md` §5.9 + §3, the post-gate hardening item #627.

## Context

The #598 air-gap-removal gate criterion §5.9 requires "measured-boot attestation." The term
"attestation" in the Policy Agent's `MeasuredBootStep` (`attestation_gate`) today covers
**security-material validation** — `_phase_attestation` (`entrypoint.py`) → `_validate_security_material`
confirms the weight manifest is present + its digest is valid, the JWT TPM signing key is provisioned,
and the per-boot CA cert is present; on any failure it refuses to start and hard-locks after 3 attempts
(`entrypoint.py:467–476`). It does **not** read TPM PCR (Platform Configuration Register) values or
produce a remotely-verifiable attestation quote — there is no PCR read anywhere in the measured-boot
path. The `boot.py:9` comment ("Verify TPM/Pluton attestation (or dev-mode skip)") overstates this.

The open question for the gate was the **scope** of "attestation": is security-material validation the
bar, or must the gate require true TPM PCR measured-boot (attesting the firmware/bootloader/OS boot-chain
integrity, detecting tampering *below* BlarAI)?

## Decision

**For the #598 air-gap-removal gate, the existing security-material validation IS the §5.9 attestation
bar.** True TPM PCR measured-boot is **deliberately deferred to a post-gate hardening item (#627)** —
tracked and designed on its own merits, not rushed to a gate date, and explicitly **not** discarded.

## Rationale

1. **Threat-orthogonality.** The #598 gate exists to clear the threat that *removing the air-gap*
   introduces: **network** attack surface. PCR measured-boot defends a **physical** threat — an attacker
   with hands on the powered-off machine altering the boot chain (evil-maid / bootkit). The two do not
   overlap: the air-gap can come down safely without PCR measured-boot, and PCR measured-boot protects
   the machine whether or not the air-gap is up. The gate's threat is not materially worsened by
   deferring a physical-tamper control. The current material-validation already fail-closes on
   forged/missing *trust material* — the vector an attacker forging network-decision trust would target.
2. **Decades-of-use operational cost demands deliberate design.** PCR values legitimately change on every
   firmware/OS update. Strict measured-boot fails-closed-on-boot until re-baselined; on a daily-driver
   across decades and hundreds of updates, that is recurring friction unless the re-baseline flow is
   carefully built (cf. BitLocker requiring a recovery key after some firmware updates). Bolting a
   "won't boot after an update" behavior onto the production system deserves its own design pass, not a
   gate-deadline rush.
3. **Matching the control to the threat is the mature posture, not the minimal one.** This is not a
   corner cut: the stronger control guards a different threat class and is captured + tracked (#627).

## Alternatives not taken

- **Require full TPM PCR measured-boot for the #598 gate** — rejected *for this gate*: a significant
  build (PCR read + expected-baseline policy + fail-closed-on-mismatch + re-baseline tooling) defending a
  threat orthogonal to air-gap removal, carrying recurring re-baseline friction that needs deliberate
  design. **Held as post-gate hardening #627**, not discarded.
- **Leave §5.9 open** — rejected: the gate cannot have an undecided criterion; the scope is now settled.

## Consequences

- **Positive:** the #598 gate bar matches the threat the gate addresses; the enforced control
  (refuse-to-start material-validation, hard-lock ×3) is real and live; the stronger control is recorded
  and tracked, not lost.
- **Accepted trade-off:** physical boot-chain tampering (evil-maid / bootkit) is **not** defended until
  #627 ships. Documented and tracked.
- **Doc-accuracy follow-up (in #627):** `services/policy_agent/src/boot.py:9` comment overstates the
  current scope ("Verify TPM/Pluton attestation"); it is aligned when #627 lands (the comment becomes
  accurate only then).

## Amendment 1 (2026-06-10) — Production keys will NOT be PCR-bound

**Status:** ACCEPTED 2026-06-10 (Lead-Architect-decided). **Informed by:** the 2026-06-09 on-chip PCR-seal PoC (`docs/security/pcr_seal_poc_2026-06-09.md` + `shared/security/verify_pcr_seal.py`), which DEMONSTRATED that a secret can be sealed under a `PolicyPCR` on this TPM and the chip refuses to unseal it when the bound PCR value differs — the key-sealing primitive is **proven feasible** on this hardware.

**Decision:** the production trust-root keys (the DEK wrapping key, the audit-signing key, the manifest-signing key, the PA JWT key) will **NOT be PCR-bound** — they will not be sealed under a `PolicyPCR` that gates their use on a measured-boot baseline. They remain TPM-resident, non-exportable, and (per #637) keystore-DACL-locked, usable whenever the TPM and the owning user context are present, **independent of boot-chain PCR state**.

**Scope — this decides the *key-sealing* variant only.** PCR-binding the keys is the *strongest* form of measured-boot enforcement (the keys themselves refuse to open in an unexpected state). It is distinct from a PCR boot-attestation *check* (read PCRs at boot, compare to a baseline, then decide). This amendment rules out the **key-sealing** form; the broader PCR boot-attestation-check remains #627's deferred-post-gate scope under the original decision above — neither advanced nor closed here.

**Rationale:**
1. **Decades-of-use brittleness — and key-sealing is the *worst* place to take it.** PCR values legitimately change on every firmware/OS update (the cost the base decision already flagged). For an attestation *check* that cost is a re-baseline prompt; for **PCR-bound keys** it is categorically worse — the keys themselves become *unusable* until re-sealed, so a routine BIOS/Windows update would brick the trust root until a recovery ceremony. On a single-user daily-driver evolving across decades and hundreds of updates, that fights head-on the key-loss-recovery posture ADR-025 requires.
2. **Threat-orthogonal and already mitigated in depth.** The threat PCR-binding closes — an attacker booting a different OS/configuration to *use* the keys — is a physical-possession + boot-tamper threat, orthogonal to the air-gap-removal (network) threat the #598 gate serves. It is already mitigated: the keys are **non-exportable and chip-bound** (cannot be extracted at all), the box is **air-gapped and physically held**, and the keystore is **owner-only-DACL'd** (#637). PCR-binding would add a brittle fourth layer against a residual sliver of that already-covered physical threat.
3. **Informed, not defaulted.** The PoC proved the primitive works on this exact chip, so this is a deliberate *"we can, and we choose not to,"* not an unproven dodge — capability demonstrated, cost weighed, declined on the record.

**Consequence:** the trust-root keys' protection posture is settled — hardware-resident + non-exportable + DACL-locked, *not* PCR-gated. The 2026-06-09 PoC stands as the recorded feasibility evidence behind the decline.

## References

`SECURITY_ROADMAP_air_gap_removal.md` §5.9 + §3; ADR-018 (TPM trust root); #598; #627 (post-gate
hardening — TPM PCR measured-boot). DECISION_REGISTER index updated in the same change (the non-optional
maintenance rule).
