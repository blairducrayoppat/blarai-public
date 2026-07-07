# ADR-018: TPM 2.0 Trust Root (SGX Replacement)

**Status:** Accepted — Lead Architect ratified 2026-06-03 ("proven core").
**Supersedes:** the SGX-attestation premise in `Use Cases_FINAL.md` §5.
**Resolves:** ISS-5 (SGX design-intent gap). **Depends on:** ISS-4 findings
(`docs/TPM_CAPABILITY_FINDINGS.md`). **Enables:** FUT-04, FUT-01, FUT-05.

## Context

BlarAI's original design (`Use Cases_FINAL.md` §5, the Agentic JWT lifecycle)
assumed **Intel SGX** enclaves + remote attestation as the hardware root of trust
for the Policy Agent. This is a **phantom capability**: Intel removed SGX from
client CPUs starting with 12th-gen Alder Lake (2021); the target hardware — Intel
Core Ultra 7 258V (Lunar Lake) — has **no SGX**. The code never used SGX, but the
design narrative implied it, so the trust root was undefined in practice.

A real hardware trust root is needed for two committed features:
- **FUT-04 / GOV-10** — a tamper-evident model-weight integrity manifest (today
  the manifest is plain JSON; anyone who can swap `openvino_model.bin` can edit
  its digest, so the "Known-Good Manifest" guarantees nothing at rest).
- **FUT-01 / GOV-01** — a CA signing key for the agent mTLS/JWT trust that cannot
  be exfiltrated from the device.

## Decision

**Adopt TPM 2.0 as the hardware trust root, accessed via the Windows CNG
*Microsoft Platform Crypto Provider*.** Trust-root key material is a
**non-exportable** signing key generated inside the TPM (private key never
leaves hardware).

ISS-4 established on the reference unit (evidence in `TPM_CAPABILITY_FINDINGS.md`):
- The active TPM 2.0 is an STMicroelectronics TPM; **Microsoft Pluton is also
  present** (Lunar Lake) but is not the active TPM. The design targets the
  **standard TPM 2.0 / CNG surface**, so it is portable across Pluton-fTPM and
  discrete-TPM units regardless.
- Non-exportable key create / sign / verify works **from userspace without
  elevation** (hardware-verified by `shared/tests/test_tpm_signer.py`).

**Scope this push ("proven core"):**
1. **FUT-04** — TPM-sign the weight-integrity manifest; verify the signature at
   boot before trusting its hashes (fully host-side).
2. **FUT-01** — seal the CA signing key as a non-exportable TPM key.
3. **FUT-05** — a provisioning + **recovery** ceremony (mandatory: a lost TPM key
   must not fail-closed-brick the system).

**Staged for a later push:** formal local **PCR-quote attestation** (proving the
boot state is untampered). The primitive (signing keys) is in place; attestation
layers on top later.

**Rejected alternatives:**
- *Intel SGX* — unavailable on this hardware class; not returning to client CPUs.
- *Cloud attestation (Windows Device Health Attestation)* — requires an external
  network call; **violates the absolute no-network runtime privacy mandate.**
- *Software-only trust (keep plain-JSON manifest, key in a file)* — no hardware
  binding; defeated by trivial file edits. This is the status quo being replaced.
- *Wait for SGX to return* — speculative; indefinite.

## Consequences

**Positive:**
- Hardware-rooted, non-exportable signing — the CA key and the weight-manifest
  authority cannot be copied off the machine.
- Tamper-evident model weights at rest (FUT-04 closes the swap-weights-and-manifest
  gap against offline / evil-maid / disk-swap threats).
- Vendor-portable (standard TPM 2.0 / CNG); no Pluton-specific API lock-in.
- No new runtime dependencies (stdlib `ctypes` → `ncrypt.dll`); no network.

**Negative / risks (on the record):**
- **Brick risk** — TPM-signed/sealed material is bound to this TPM; a TPM clear,
  key loss, or hardware change makes verification fail-closed. **FUT-05's
  recovery ceremony is non-optional**, and enforcement rolls out behind a flag
  (warn-only → enforce after a live-verified signed boot).
- **Threat-model boundary (honest):** TPM-signing defends **at rest**, not against
  an attacker with code execution on the host as the BlarAI user (who could ask
  the TPM to re-sign). Closing that needs PCR-binding / key-use policy — part of
  the deferred attestation stage.
- **Bus-sniffing:** a discrete bus-connected TPM is more exposed to physical
  TPM-bus sniffing than the SoC-integrated Pluton; making Pluton the platform TPM
  is a future hardening (firmware change; clears the TPM) — noted, not actioned.
- **Host-vs-VM (FUT-01):** the Policy Agent runs in the Alpine VM but the TPM is on
  the host. Whether the host signs on the VM's behalf (vsock) or a Hyper-V vTPM is
  exposed to the VM is an open sub-decision; FUT-04 does not depend on it.

## Implementation

- Primitive: `shared/security/tpm_signer.py` (`is_available`, `ensure_key`,
  `sign`, `verify`, `export_public_key`, `delete_key`) — Fail-Closed off-Windows,
  hardware-tested (`shared/tests/test_tpm_signer.py`, `@pytest.mark.slow`).
- Consumers (this push): the weight-integrity verification path
  (`shared/models/weight_integrity.py`, invoked host-side from
  `launcher/__main__.py`).
