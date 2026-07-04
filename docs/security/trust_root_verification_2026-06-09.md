# BlarAI Trust-Root On-Chip Verification — 2026-06-09

**Verdict: ALL FOUR TRUST-ROOT KEYS VERIFIED-LIVE.**
Claim upgrade: **INFERRED → VERIFIED-LIVE.**

Machine-readable companion: [`trust_root_verification_2026-06-09.json`](trust_root_verification_2026-06-09.json).

---

## What this proves

BlarAI's whole security posture re-roots on four TPM (Trusted Platform Module)
keys held inside the platform chip. Until today, the capstone deck (#612) and the
`SECURITY_ROADMAP` honestly graded one fact as **inferred, not proven**: *that the
four keys are physically resident in the chip* was read off the provisioning
scripts and the boot preflight (which only proves each key **exists**), never off
the chip itself. This run closes that gap by exercising each key **on the real
chip** and recording the result.

For each of the four keys we proved three properties, **directly and per key**:

| Property | How it was proven (read-only) |
|---|---|
| **Resident** | `key_exists()` — the named key is present in the platform TPM. |
| **Functional** | The key actually *works on the chip*: the three signing keys sign a fixed test message and verify it (ECDSA P-256); the seal key wraps and unwraps a **throwaway** 32-byte random blob (RSA-2048 OAEP-SHA-256). |
| **Non-exportable** | A direct private-key export is **refused** by the provider — a `NCryptExportKey` for the *private* blob returns a non-success status. This is the exact call the existing hardware tests make, pointed at the **production** key handles. |

All four keys returned `resident=true`, `functional_roundtrip=true`,
`private_export_refused=true` → **`VERIFIED_LIVE`**.

| Key | Type | Role | Verdict |
|---|---|---|---|
| `BlarAI-PA-JWT-Signing` | ECDSA P-256 | Policy Agent JWT minting | VERIFIED_LIVE |
| `BlarAI-Audit-Signing-Key-v1` | ECDSA P-256 | tamper-evident audit stream | VERIFIED_LIVE |
| `BlarAI-Manifest-Signing` | ECDSA P-256 | weight-integrity manifest (FUT-04) | VERIFIED_LIVE |
| `BlarAI-DEKSeal` | RSA-2048 | at-rest DEK envelope (ADR-025) | VERIFIED_LIVE |

---

## The non-export sharpening (why this is a *true per-key* proof)

The original brief proposed sourcing "non-exportable" from the existing `@slow`
hardware tests. On review those tests prove non-export **directly but on ephemeral
`…-PytestHW` keys** they create and delete — not on the four production keys. That
made "non-exportable" a *verified-by-equivalence* inference for the real keys (they
share the no-`NCRYPT_ALLOW_EXPORT` creation path), not a direct per-key proof.

For a trust-root claim whose whole point is "*these specific keys* can't leave the
chip", the LA directed the stronger version: a **direct per-production-key**
private-export attempt, asserted refused. That is what `verify_trust_root.py` does
(`ECCPRIVATEBLOB` for the ECDSA keys, `RSAFULLPRIVATEBLOB` for the RSA key). A
refused export reads-and-fails and **mutates nothing**; had any export *succeeded*,
that would be surfaced loudly as `CRITICAL_EXPORTABLE`. None did.

---

## Read-only discipline

This was a **verification, never a (re-)provisioning**. The probe
(`shared/security/verify_trust_root.py`) calls only read-only primitives —
`is_available`, `key_exists`, `sign`, `verify`, `export_public_key`, and
`TpmSealer(auto_provision=False).seal/.unseal`. It calls **no** `ensure_key`, **no**
`delete_key`, **no** `NCryptCreatePersistedKey`, and **no** provisioning script.
`auto_provision=False` is mandatory on the sealer — the default `True` would call
`ensure_key()` and *create* the key. The functional seal round-trip uses
`os.urandom(32)`, **never** the real DEK and **never** the keystore file.

This session ran in an **elevated (administrator) shell** — the same context the
provisioning/boot path uses, which is why all four keys open from here. Under
elevation a stray mutating call would actually succeed against the real trust root,
so the no-mutation discipline is *more* load-bearing, not less; it was held
absolutely.

---

## Corroboration

- **Hardware tests (14 passed, 42 deselected, 3.47 s):**
  `pytest shared/tests/test_tpm_signer.py shared/tests/test_tpm_sealer.py shared/tests/test_tpm_record_signer.py shared/tests/test_verify_trust_root.py -m slow`
  — includes the pre-existing per-primitive non-export assertions, the **production
  audit key's** real sign/verify round-trip (`test_tpm_record_signer` Group R —
  read-only: `ensure_key` no-ops on the pre-provisioned key, no delete), and the new
  `verify_trust_root` probe logic validated on **ephemeral** keys (never the four
  production keys).
- **Ceremony preflight: READY for production boot** — all 9 checks OK (four keys
  present, DEK keystore present, `certs/pa_public.pem` present, production manifest
  digest verified).

---

## Reproduce

```
python -m shared.security.verify_trust_root          # human checklist + JSON
python -m shared.security.verify_trust_root --json    # JSON only
```

Re-runnable at every gate and every hardware generation. Locked by the `@slow`
hardware test `shared/tests/test_verify_trust_root.py` (deselected from the standing
gate; run with `-m slow`).

### Hardware / environment (community-grade, reproducible)

- **CPU:** Intel Core Ultra 7 258V (Lunar Lake)
- **TPM:** STMicroelectronics (STM), firmware 9.256.0.0, TPM 2.0 / spec 1.59
  (`ACPI\MSFT0101`). Microsoft Pluton is also present (`PCI\VEN_8086&DEV_A862`) but
  is not serving as the TPM role. (Source: `docs/TPM_CAPABILITY_FINDINGS.md`.)
- **OS:** Windows 11 Pro (10.0.26200). `platform.platform()` reports
  `Windows-10-10.0.26200-SP0` — a known platform-string quirk on Windows 11.
- **Crypto provider:** Microsoft Platform Crypto Provider (Windows CNG).
- **Python:** 3.11.9.
- **Verified at (UTC):** 2026-06-09T16:36:46Z.

### Not measured (named, not implied)

- Per-operation TPM latency (tracked separately under `PERFORMANCE_LOG.md` /
  `docs/performance/`; the hot-path budget is GOV-10).
- PCR-binding / measured-boot key policy — these keys are not PCR-bound; that is a
  future attestation increment (`TPM_CAPABILITY_FINDINGS.md` §2/§3).
- Whether the **production** keys are reachable from a *non-elevated* shell — not
  established here and not required (the boot path runs elevated).

---

## Scope — what this does and does not do

This **scopes the trust-root verification criterion only.** It upgrades one
load-bearing capstone claim from inferred to verified-live. It does **not** open the
#598 air-gap GO/NO-GO gate, which still gates on the #612 capstone phase
(`SECURITY_ROADMAP` §5.13) + the LA sign-off (§5.12), the #106 signed-manifest
runtime remainder, the DORMANT egress machinery (post-#556), and #607.

## Downstream

- **Capstone deck (handed to the deck-builder; not edited here):** in
  `deck_outline.json`, move the "four TPM keys physically chip-resident is
  **INFERRED**" clause from the §K *NOT-verified* list to *VERIFIED-LIVE* (keeping
  the other three NOT-verified items), regrade the trust-root slide from "TESTED, not
  VERIFIED-LIVE" to "VERIFIED-LIVE", drop the transformation-slide "disk-inferred"
  caveat, and re-render the HTML / summary. Cite this artifact.
- **Stale-doc finding (surfaced, not edited — out of session write-scope):**
  `SECURITY_ROADMAP_air_gap_removal.md` §"TPM key state" (dated 2026-06-07) marks
  `BlarAI-Manifest-Signing` "NOT PROVISIONED" and "preflight does not yet probe for
  it" — both now false. Recommend a one-line update to VERIFIED-LIVE (2026-06-09)
  citing this artifact.

*Tracked: Vikunja #635. References: ADR-018, ADR-021, ADR-025;
`docs/TPM_CAPABILITY_FINDINGS.md`.*
