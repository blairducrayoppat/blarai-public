### 2026-06-09 — The PCR seal, and the door Windows wouldn't let me forge

The ask was four words: "test Pluton PCR-seal." The first useful thing was to not
take them literally. The premise — that Pluton seals to PCRs on this box — has been
false and documented-as-false since 2026-06-03: Pluton is present
(`PCI\VEN_8086&DEV_A862`) but the TPM 2.0 role is filled by a discrete
STMicroelectronics chip, which is what `TPM_CAPABILITY_FINDINGS.md` was renamed to
say. BitLocker already proves PCR-sealing works here (PCR7 bound), and yesterday's
trust-root run proved BlarAI's own keys are chip-resident and functional. So the
honest target wasn't "Pluton" — it was the one PCR claim the repo had carried as
*feasible but unproven*: that BlarAI can seal a secret under a PCR **policy** and
have the chip refuse to unseal it when the measured state differs. That last clause
is the whole point of measured boot, and it had never been exercised on the metal.

The build is a raw-TBS TPM 2.0 probe, deliberately not the CNG path the rest of
`shared/security/` uses — the Microsoft Platform Crypto Provider wraps keys but
won't express a *data object sealed under PolicyPCR*, so I hand-marshalled the
TPM2 command bytes over `tbs.dll` (stdlib ctypes, no new dependency, and as it
turned out, no elevation). CreatePrimary in the NULL hierarchy, a trial session to
compute the PolicyPCR digest, Create the keyedhash sealed blob, Load, then a real
policy session to Unseal. It came up green on the first genuinely-end-to-end run:
the secret sealed to PCR 23's current value unsealed and round-tripped byte-for-byte.

The negative test is where it got interesting. My first design was the dynamic one —
extend the live PCR, watch the same object refuse to open. The TPM said
`TPM_E_COMMAND_BLOCKED`. Windows TBS blocks a user-mode `PCR_Extend` outright. My
reflex was "find the way around it"; the right read was the opposite. That block is
not in my way — it *is* the property I'm trying to prove. A measured-boot seal is
only worth anything because a process cannot reach in and forge PCR state through the
OS, and here was Windows enforcing exactly that, in my face, with an error code. So I
stopped trying to mutate a PCR and proved the binding the clean way instead: seal a
second object to a *different* PCR-23 value and show it will not open in the current
state. Same enforcement, and it mutates no PCR at all — the PoC only ever reads PCR
23. The chip refused the mismatched object with `TPM_RC_POLICY_FAIL (0x09D)`, and the
two objects' policy digests are asserted to differ so the refusal can't be hand-waved
as binding-to-garbage. The blocked extend went into the record as a finding, not a
footnote.

Everything stayed transient and throwaway by construction — NULL-hierarchy parent,
transient sealed objects, an `os.urandom(32)` secret that is never a real key, PCR 23
(the resettable Application-Support register, no boot measurement) read but never
written. Two consecutive runs both returned DEMONSTRATED with no TPM slot leak. The
"feasible, not proven" caveat in `TPM_CAPABILITY_FINDINGS.md` §2/§3 and the
"Not measured: PCR-binding" line in the trust-root artifact can now both be retired.

**Proposed lesson:** *When the platform refuses your test action, the refusal may be
the very property you set out to prove — reframe the block as evidence, don't engineer
around it.* I almost spent the session fighting `TPM_E_COMMAND_BLOCKED` instead of
recording it as the thing that makes a PCR seal trustworthy in the first place. Pairs
with verifying the premise before building: the literal task named the wrong chip, and
the literal negative test named the wrong obstacle, and both corrections came from
reading what the system was actually telling me rather than what the brief assumed.

**Next:** a harden-or-leave decision for the LA — promote `verify_pcr_seal.py` to a
committed, `@slow`-locked verification tool in the `verify_trust_root.py` mould
(re-runnable at every gate / hardware generation), or leave it as the standalone PoC
it is now. Either way, *binding the production trust-root keys to PCRs* remains the
separate ADR-028 / #627 measured-boot-attestation decision this run de-risks but does
not make. This proves the primitive on the hardware; it does not open #598.

*(artifact: `shared/security/verify_pcr_seal.py` + `docs/security/pcr_seal_poc_2026-06-09.{json,md}`;
uncommitted PoC pending the harden-or-leave call; Vikunja #627; references ADR-018, ADR-028,
`TPM_CAPABILITY_FINDINGS.md`, `trust_root_verification_2026-06-09.md`.)*
