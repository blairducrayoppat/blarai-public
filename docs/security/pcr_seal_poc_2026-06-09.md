# TPM 2.0 PCR-Bound Seal/Unseal — On-Chip Proof-of-Concept — 2026-06-09

**Verdict: PCR-BOUND SEAL/UNSEAL DEMONSTRATED on this hardware.**
Claim upgrade for the measured-boot key-policy primitive: **FEASIBLE (unproven) → DEMONSTRATED.**

Machine-readable companion: [`pcr_seal_poc_2026-06-09.json`](pcr_seal_poc_2026-06-09.json).
Probe: [`shared/security/verify_pcr_seal.py`](../../shared/security/verify_pcr_seal.py).

---

## What this proves

`TPM_CAPABILITY_FINDINGS.md` §2/§3 graded PCR-binding as *"feasible via `NCRYPT_PCP_*`
policy properties — a further increment, not proven in this PoC"*, and
`trust_root_verification_2026-06-09.md` listed *"PCR-binding / measured-boot key
policy — these keys are not PCR-bound; that is a future attestation increment"*
under **Not measured**. This run closes that specific gap by exercising a real
PCR-bound seal on the chip:

> A secret can be **sealed** under a TPM 2.0 policy bound to a Platform
> Configuration Register (PCR) value, **unsealed** while the live PCR matches that
> value, and the unseal **refused** when the bound value is not the live one — the
> measured-boot binding enforces, it does not merely decorate.

| Test | Construction | Result |
|---|---|---|
| **Positive** | Seal `os.urandom(32)` under `PolicyPCR(PCR 23 == current value)`; unseal in the current state. | `TPM_RC_SUCCESS`, secret round-trips byte-for-byte → **PASS** |
| **Negative** | Seal the same secret under `PolicyPCR(PCR 23 == a different value)`; attempt unseal in the current state. | `TPM_RC_POLICY_FAIL (0x09D)`, unseal refused → **PASS** |

The two objects differ **only** in the bound PCR value (their `authPolicy` digests
are asserted to differ — `policies_differ = true`), so the refusal is caused by the
PCR binding, not by binding to an unsatisfiable/garbage policy. This is the same
enforcement property a measured-boot seal relies on: *a secret sealed to one
platform state will not open in a different state.*

### Measured values (this boot)

- PCR 23 (SHA-256), live: `00…00` (all-zeros — nothing extended PCR 23 this boot).
- `authPolicy(current state)` : `3c87a4b3fb85ebeea58c5fb36ac22d3f280cec27a9f6dd0fa23be9ce560deec8`
- `authPolicy(different state)`: `00cee3d64f0edfaed78bc18c487b7716e3903038017cd15a81e27975dd6af21a`
- Transient parent handle: `0x80FFFFFF` (NULL hierarchy).

## The blocked-extend finding (why the negative test binds a value instead of extending a PCR)

The first-cut negative test was the dynamic form — *extend the live PCR, then watch
the same object fail to unseal*. On this platform a user-mode `TPM2_PCR_Extend`
submitted through TBS returns **`TPM_E_COMMAND_BLOCKED` (0x80280400)**. That block is
not an obstacle to route around quietly — it **is** the protection that makes
measured boot worth sealing to: an ordinary process cannot forge PCR state through
the OS TPM interface. So the negative test instead binds the second object to a
*different* PCR-23 value and shows it will not open in the current state — proving
the same enforcement while **mutating no PCR at all** (PCR 23 is only read).

## Read-only / non-destructive discipline

- **Transient parent**: a primary key in the **NULL hierarchy** — ephemeral, empty
  auth, gone on context close / reboot. Nothing persistent is created in any
  hierarchy; the production trust-root keys are never touched.
- **Transient sealed objects**: created, loaded, and flushed within the run.
- **No PCR is modified.** PCR 23 is read; the lone extend attempt is the
  (blocked, recorded) probe above.
- **Throwaway secret**: `os.urandom(32)`, never a real key or DEK.
- **Re-runnable**: two consecutive runs both returned `DEMONSTRATED` with no TPM
  resource leak (transient object/session slots are flushed each run).

## Reproduce

```
python shared/security/verify_pcr_seal.py            # human report (exit 0 = DEMONSTRATED)
python shared/security/verify_pcr_seal.py out.json    # + machine-readable JSON
```

### Hardware / environment (community-grade, reproducible)

- **CPU:** Intel Core Ultra 7 258V (Lunar Lake).
- **TPM:** STMicroelectronics (STM), firmware 9.256.0.0, TPM 2.0 / spec 1.59
  (`ACPI\MSFT0101`). Microsoft Pluton is also present (`PCI\VEN_8086&DEV_A862`) but
  is **not** serving as the TPM role — the PCR-sealing engine here is the discrete
  ST TPM. (Source: `docs/TPM_CAPABILITY_FINDINGS.md`.)
- **OS:** Windows 11 Pro 10.0.26200.
- **TPM interface:** raw TPM 2.0 commands over **TBS** (`tbs.dll`:
  `Tbsi_Context_Create` / `Tbsip_Submit_Command`), stdlib `ctypes` only — no new
  dependencies, and **no elevation** (this PoC ran in a standard-user shell).
- **PCR bank / index:** SHA-256, PCR 23 (resettable Application-Support register;
  carries no boot measurement).
- **Python:** 3.14.3.
- **Verified at (UTC):** 2026-06-10T04:25:52Z (local evening of 2026-06-09).

### Not measured (named, not implied)

- **Cross-boot durability.** The parent is the ephemeral NULL-hierarchy primary, so
  this proves the seal/unseal *primitive*, not persistence across a reboot. A
  durable measured-boot seal would bind under a persistent hierarchy
  (owner/endorsement) — a further increment.
- **Binding to real boot PCRs (0–7 / 11) under an actual boot-state change.** That
  needs a reboot with a deliberately altered measured component, and user-mode
  `PCR_Extend` is blocked anyway — out of scope here.
- **Latency / throughput.** This is a capability test, not an inference benchmark;
  no GPU / OpenVINO is involved.
- **Whether the production trust-root keys *should* be PCR-bound.** That is the
  ADR-028 / Vikunja #627 design decision this PoC *informs*, not decides.

## Scope — what this does and does not do

This **proves the PCR-bound seal/unseal primitive on this hardware.** It removes the
"feasible but unproven" caveat from `TPM_CAPABILITY_FINDINGS.md` §2/§3 and the
"Not measured: PCR-binding" line in `trust_root_verification_2026-06-09.md`. It does
**not** open the #598 air-gap GO/NO-GO gate, and it does **not** by itself PCR-bind
any production key — that remains the **#627 / ADR-028** measured-boot attestation
work (post-#598 hardening), which this PoC de-risks.

*Tracked: Vikunja #627. References: ADR-018, ADR-028; `docs/TPM_CAPABILITY_FINDINGS.md`,
`docs/security/trust_root_verification_2026-06-09.md`.*
