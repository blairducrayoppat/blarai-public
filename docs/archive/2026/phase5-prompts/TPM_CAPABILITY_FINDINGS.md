---
title: TPM_CAPABILITY_FINDINGS
status: archived
area: portfolio
---

# TPM 2.0 Capability Findings (ISS-4)

*Deliverable for Vikunja ISS-4 (#101), which requested `docs/PLUTON_CAPABILITY_FINDINGS.md`.
Renamed to `TPM_CAPABILITY_FINDINGS.md` because the load-bearing finding concerns the
active **TPM 2.0** interface (manufacturer STMicroelectronics) — a *distinct* device
from the Microsoft Pluton security processor that is **also present** on this unit.
Both are real and both enumerate in Device Manager; see §1.*

**Date:** 2026-06-03 · **Hardware:** Intel Core Ultra 7 258V (Lunar Lake) ·
**Method:** read-only `tpmtool getdeviceinformation` + a non-exportable-key
proof-of-concept via the Windows CNG *Microsoft Platform Crypto Provider*
(create → sign → verify → export-refused → delete). All probes run as a
standard (non-elevated) user.

## Summary (for the impatient)

- **Microsoft Pluton IS present** on this unit (Device Manager → Security devices →
  *"Microsoft Pluton security processor #1"*, `PCI\VEN_8086&DEV_A862`, Intel Lunar
  Lake). Separately, the **active TPM 2.0 interface** Windows uses for crypto
  (`ACPI\MSFT0101`) reports manufacturer **STMicroelectronics** — so on this unit
  the *TPM 2.0 role* is filled by an ST TPM while Pluton is present as a distinct
  security processor. **This does not block anything** — the CNG Platform Crypto
  Provider binds to the active TPM 2.0, which presents the same standard Windows
  interface regardless of vendor.
- **The trust-root primitive works on this hardware, from userspace, without
  elevation:** a non-exportable, TPM-backed signing key (ECDSA P-256) was
  created, used to sign + verify, and its private key export was *refused* by
  the provider. This is the exact primitive FUT-01 and FUT-04 require.
- **Design correction:** target the **standard Windows TPM 2.0 / CNG Platform
  Crypto Provider** surface, *not* Pluton-specific APIs. The design is then
  portable across Pluton-fTPM and discrete-TPM units.
- **SGX is dead on this class of hardware** (removed from Intel client CPUs since
  Alder Lake; Lunar Lake has none). The trust root must re-root on TPM 2.0 — this
  is the ISS-5 decision, now backed by concrete evidence.

## 1. Hardware reality — Pluton IS present; the active TPM 2.0 is an ST TPM

`tpmtool getdeviceinformation` (no elevation):

| Field | Value |
|---|---|
| TPM Present / Initialized | True / True |
| TPM Version / Spec | 2.0 / 1.59 |
| **Manufacturer** | **STMicroelectronics ("STM")**, FW 9.256.0.0 |
| Ready For Attestation | **True** |
| Is Capable For Attestation | **True** |
| Bitlocker PCR7 Binding State | **Bound** (measured boot active) |
| TPM Has Vulnerable Firmware | **False** |
| Lockout | Not locked out; MaxAuthFail 32, interval 7200s |

**Device Manager / PnP confirms two distinct security devices** (`Get-PnpDevice
-Class SecurityDevices`):

| Device | InstanceId | Role |
|---|---|---|
| Trusted Platform Module 2.0 | `ACPI\MSFT0101\1` | **active TPM 2.0** — manufacturer field = STM (above) |
| Microsoft Pluton security processor #1 | `PCI\VEN_8086&DEV_A862` | **Pluton present** (Lunar Lake), not serving as the TPM here |

So **Pluton is present** on this machine (as the marketing and Device Manager
indicate); the *TPM 2.0 role* is simply filled by an ST TPM rather than by
Pluton-acting-as-the-TPM. (`ACPI\MSFT0101` is the generic Windows TPM-2.0 ACPI ID
and does **not** denote the vendor — the vendor is read from the TPM's own
manufacturer field, which is STM. The `Win32_Tpm` WMI class returns *Access
denied* without elevation, so the manufacturer reading here comes from the
no-elevation `tpmtool` path.)

The architecture's "Pluton" framing (GOV-01, GOV-10, FUT-01/04, ISS-5) should be
read as **"the TPM 2.0 trust root"**: target the standard **Windows TPM 2.0 via
CNG**, which binds to the active TPM (the ST chip here) and stays portable across
Pluton-fTPM and discrete-TPM units. **Threat-model note (unconfirmed, not an
action):** if the active ST TPM is a *discrete bus-connected* chip, it is
theoretically more exposed to physical TPM-bus sniffing than the SoC-integrated
Pluton; making Pluton the platform TPM is a firmware-level option with better
bus-attack resistance, but it clears the TPM (breaks BitLocker) and is out of
scope for this work.

## 2. Capability proof-of-concept (the FUT-01/FUT-04 primitive)

Via `System.Security.Cryptography.CngKey` against the **Microsoft Platform Crypto
Provider** (the TPM-backed CNG key-storage provider):

```
Created key: provider=Microsoft Platform Crypto Provider  algo=ECDSA
             export-policy=None  (elevated=False)
Sign+verify with hardware key: True  (sig 64 bytes)
Private-key export REFUSED -> non-exportable confirmed
Test key deleted (cleanup ok)
```

- **Non-exportable hardware key:** `ExportPolicy=None` + a private-key export
  attempt *refused* by the provider ⇒ the private key is sealed in the TPM and
  cannot be extracted, even by the creating process.
- **No elevation required** for create / sign / verify / delete (per-user CNG
  key). `Get-Tpm` (the cmdlet) *does* require admin, but the crypto operations
  the trust root needs do not.
- ECDSA P-256 proven; RSA-2048 is also supported by the same provider (the GOV-01
  CA-key options). Signatures are usable for JWT/cert minting and manifest
  signing alike.

## 3. ISS-4 questions answered

1. **API surface from userspace:** Windows CNG **Microsoft Platform Crypto
   Provider** (NCrypt/CNG; reachable via .NET `CngKey` or, dependency-free, via
   `ctypes` → `ncrypt.dll`). DPAPI-NG can layer on it. Per-user keys need no
   elevation. PCR indices: PCR 7 is in active measured-boot use (BitLocker
   binding confirmed); PCR 0/2/4/11 are standard Windows measured-boot banks and
   are bindable via a key's TPM policy.
2. **Key sealing feasibility:** **Confirmed.** A CA private key (EC P-256 or
   RSA-2048) can be generated *inside* the TPM and marked non-exportable
   (proven). Binding to PCRs (PCR 7/11) is feasible via `NCRYPT_PCP_*` policy
   properties — a further increment, not proven in this PoC. Firmware-update
   behaviour: PCR-bound material may require re-seal after a measured-boot change
   — this is exactly why a **provisioning/recovery ceremony (FUT-05)** is
   mandatory before sealing the *real* CA key (lose-the-key = fail-closed brick
   without a recovery path).
3. **Attestation:** TPM reports Ready/Capable for attestation. **Local** PCR-quote
   attestation (TPM signs a PCR digest with an attestation key; a local verifier
   process checks it) is the privacy-mandate-compatible path. Windows Device
   Health Attestation is **cloud-oriented → rejected** (no external network,
   per the runtime privacy mandate). Local quote → local verifier is feasible.
4. **Practical constraints:** No Windows Hello requirement for CNG provider keys.
   Secure Boot + measured boot are active (PCR7 bound). Crypto ops do **not**
   require elevation. Operation latency was sub-second in the PoC — well inside
   the \~200–500 ms per-adjudication budget (GOV-10); per-op TPM signing is the
   item to benchmark before it lands on the adjudication hot path.

## 4. Implementation path

- **Primitive (foundation, decision-independent):** a host-side, Windows-only
  `ncrypt.dll` (`ctypes`) wrapper — create/open non-exportable TPM signing keys,
  sign, verify, export public key, delete. Fail-closed if no TPM / not Windows.
  Needed identically under every ISS-5 option. *No new dependencies.*
- **FUT-04 / GOV-10 (cleanest first feature — fully host-side):** TPM-sign the
  weight-integrity manifest (`manifest.json`) with a non-exportable TPM key;
  verify the signature at boot *before* trusting the manifest's SHA-256 hashes.
  Closes the "attacker swaps weights **and** manifest" gap. Weight verification
  already runs host-side (`shared/models/weight_integrity.py`, called from
  `launcher/__main__.py`), so there is no VM/vTPM question here.
- **FUT-01 (CA key) — has an architecture wrinkle:** the Policy Agent (which mints
  JWTs) runs in the Alpine VM, but the TPM is on the host. Options: host signs on
  the VM's behalf over vsock, or a Hyper-V **vTPM** is exposed to the Gen-2 VM.
  This is part of the ISS-5 / trust-root architecture decision.

## 5. Decisions this unblocks (for the Lead Architect)

- **ISS-5 — trust-root attestation mechanism (SGX → ?).** Recommendation, given
  the privacy mandate + this hardware: **local TPM 2.0 PCR-quote attestation +
  non-exportable TPM signing keys, no cloud.** SGX documented as unavailable on
  client hardware (not coming back). ADR to record it.
- **Host-vs-VM TPM for the CA key (FUT-01):** host-signs-over-vsock vs Hyper-V
  vTPM. (FUT-04 does not need this resolved.)
- **FUT-05 — provisioning & recovery ceremony.** Non-optional before sealing the
  real CA key: how the TPM key is provisioned, rotated, and *recovered* if the
  TPM/key is lost (else fail-closed bricks the system).

## 6. Other Lunar Lake security blocks (SSE, GSC) — relevance to BlarAI

Lunar Lake's Platform Controller Tile carries more security blocks than the
TPM/IPSE: the **Silicon Security Engine (SSE)**, the **Graphics Security
Controller (GSC)**, and **CSME**. They split into two categories:

- **Transparent platform security (no app API — benefited passively).** SSE, GSC,
  and CSME protect the platform automatically; BlarAI gains from them by *running
  on a secured platform*, not by calling them. There is nothing to "integrate."
- **App-usable surface.** Essentially just the **TPM 2.0** (which IPSE/Pluton can
  back) — the one thing BlarAI actively uses (ADR-018).

**Silicon Security Engine (SSE)** — the silicon **root of trust** (secure firmware
loading, boot measurements, on-die CA). It is the (previously unnamed) root the
design's "Measured Boot Phase 0" already stands on. Its host interface
(**ISSEI**, system measurements over **SPDM**) is a concrete **candidate
measurement source for the PCR-quote attestation stage ADR-018 deferred** — i.e.,
SSE is a future *active* attestation option, not a current integration gap.
Windows-side ISSEI access is unconfirmed (a Linux driver exists); verify if/when
the attestation stage is built.

**Graphics Security Controller (GSC)** — GPU-side security (firmware integrity /
isolation; detailed scope in Intel-confidential datasheets). It is **not** the
lever for BlarAI's GPU-data threat: protecting model/inference *data in iGPU
memory* from host-level scraping is **TDX Connect / TDISP's** domain, already in
the design as a conditional enhancement (ADR-007, ISSUE-008). GSC is GPU
firmware/content protection, benefited passively.

**Design impact:** name SSE as the measured-boot root + staged-attestation
candidate (above); **no new SSE/GSC integration is warranted** — both are
transparent silicon, and the one GPU-data mechanism that needs a decision (TDX
Connect) is already tracked. Recorded per LA question, 2026-06-03.
