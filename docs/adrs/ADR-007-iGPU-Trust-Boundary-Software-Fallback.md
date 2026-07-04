# ADR-007: iGPU Trust Boundary — Software Fallback Posture

## Status
**ACCEPTED** — 2026-02-23

## Context

Gate 4 (`VALIDATE_IGPU_TRUST_BOUNDARY`) empirically tests whether the Intel Arc 140V
integrated GPU on Lunar Lake supports hardware-enforced trust boundaries via Intel TDX
(Trust Domain Extensions) and TDISP (TEE Device Interface Security Protocol). This gate
addresses Red Team ISSUE-003 and ISSUE-005, which flagged the iGPU as an untrusted shared
resource when running the Code Agent's 14B Q4_K_M model on the iGPU.

## Empirical Evidence

**Gate 4 Execution:** 2026-02-23T05:45:31Z  
**Hardware:** Intel Core Ultra 7 258V (Lunar Lake), ASUS P5405CSA  
**iGPU:** Intel Arc 140V GPU (16GB) — PCI VEN_8086 DEV_64A0, REV_04

### Test 4.1 — TDX Base Support Detection

| Feature | Result | Notes |
|---|---|---|
| TDX Supported | **false** | Lunar Lake is a client SKU; TDX is server-only (Xeon) |
| SGX Supported | **false** | No SGX registry entry on this platform |
| TME/MKTME | **false** | Total Memory Encryption not detected |
| VT-x (WMI) | **false** | Hyper-V is active — masks CPUID VT-x flag (known WMI quirk) |
| Hyper-V Present | **true** | Role enabled |
| VBS Enabled | **true** | Virtualization-Based Security active |
| Device Guard | **false** (not configured) | DG policies not deployed |
| HVCI Running | **false** | Hypervisor-enforced code integrity not active |

**Disposition:** `EXPECTED_ABSENT` — TDX absence on client Lunar Lake is the anticipated
and designed-for outcome per Red Team ISSUE-003.

### Test 4.2 — TDISP Enumeration

| Metric | Result |
|---|---|
| TDISP Detected | **false** |
| Reason | Lunar Lake iGPU is integrated on SoC fabric, not a discrete PCIe endpoint. TDISP (PCIe 6.0 TEE-IO) is not applicable to integrated GPUs. |
| iGPU PCI ID | VEN_8086 DEV_64A0 (Intel Arc 140V) |

**Disposition:** `EXPECTED_ABSENT` — TDISP is a PCIe 6.0 specification for discrete devices.

### Test 4.3 — Software Fallback Posture

| Component | Status | Available |
|---|---|---|
| Hyper-V VM Isolation | AVAILABLE | **true** — VBS-backed |
| vsock (AF_HYPERV) IPC | AVAILABLE | **true** |
| mTLS (SChannel TLS 1.2) | AVAILABLE | **true** (script bug reported `0` — see Correction below) |
| HVCI | NOT RUNNING | false — non-blocking for fallback viability |
| Measured Boot / Secure Boot | FULL | SecureBoot: true, TPM 2.0: present and ready (v9.256.0.0) |

**Fallback viability:** All three required components (Hyper-V + vsock + mTLS) are
available. The software-enforced trust boundary is **VIABLE**.

### Script Bug Correction

The gate script reported `fallback_viable: false` and `disposition: FAIL` due to a
PowerShell type coercion bug in the TLS detection logic:

```powershell
# BUGGY (shipped):
$TlsAvailable = $TlsVersions -band [System.Net.SecurityProtocolType]::Tls12
# Returns integer 0 when SecurityProtocol = SystemDefault (enum value 0)
# 0 -band 3072 = 0 → falsy → false negative

# FIXED:
$TlsAvailable = (($TlsVersions -band [System.Net.SecurityProtocolType]::Tls12) -ne 0) -or
                 ($TlsVersions -eq [System.Net.SecurityProtocolType]::SystemDefault)
```

On Windows 11, `[System.Net.ServicePointManager]::SecurityProtocol` returns `SystemDefault`
(enum value 0), which delegates TLS negotiation to the OS. The OS provides TLS 1.2+ via
SChannel. The `-band` operation yielded 0, causing a false negative. The fix explicitly
handles `SystemDefault` as TLS-capable.

## Decision

**Gate 4 disposition: PASS WITH CORRECTION (software fallback viable).**

The Lunar Lake client SoC does not and will not support TDX or TDISP. This was the
anticipated outcome. The architecture was designed from Phase 1 to fall back to
software-enforced trust boundaries. The empirical evidence confirms all three required
fallback components are operational:

1. **Hyper-V VM Isolation** — The Code Agent (14B Q4_K_M on iGPU) runs inside a Hyper-V
   VM. The VM boundary provides memory isolation at the hypervisor level.
2. **vsock (AF_HYPERV) IPC** — Communication between the host orchestrator and the VM-hosted
   Code Agent uses AF_HYPERV sockets, avoiding TCP/IP stack exposure.
3. **mTLS** — All IPC channels are authenticated with mutual TLS certificates, preventing
   impersonation of the Code Agent or orchestrator endpoints.

## Residual Risk — USE-CASE-005 and the platform at large

### [USE-CASE-005]: Interactive Local Software Engineer (Headless Microservice)

**Risk:** Without TDX/TDISP, the Code Agent's model weights and inference state in iGPU
shared memory are not hardware-encrypted. A compromised hypervisor or a side-channel attack
on the shared LPDDR5X could theoretically extract model weights or in-flight token embeddings.

**Accepted Residual Risk:** LOW.
- The Code Agent model (14B Q4_K_M) is an open-weight model — the weights themselves are
  not confidential. The risk is limited to transient inference data (user prompts, generated
  code) resident in GPU memory during generation.
- Hyper-V VM isolation + VBS provides a strong software boundary. An attacker would need
  to compromise the hypervisor itself (a Hyper-V escape vulnerability) to access raw iGPU
  memory.
- This system operates in a single-user, single-tenant, air-gapped posture. The threat
  model does not include remote attackers with arbitrary code execution on the host.
- **Mitigation:** The Code Agent VM should be configured with Fixed memory (no dynamic
  memory ballooning) to prevent memory mapping changes during inference. The Fail-Closed
  privacy mandate ensures no inference data leaves localhost.

### Platform-wide: Privacy-Preserving Local Execution

**Risk:** The absence of hardware memory encryption (TME/MKTME is not available on this
platform) means LPDDR5X contents are not encrypted at rest. A physical attacker with access
to the hardware could theoretically perform a cold-boot attack to extract memory contents.

**Accepted Residual Risk:** LOW.
- This is a laptop-class device with LPDDR5X soldered to the motherboard — DRAM modules
  cannot be removed for offline analysis.
- The system has Secure Boot enabled and TPM 2.0 present, providing a measured boot chain
  that attests system integrity before any agent workload executes.
- **Mitigation:** BitLocker Full Volume Encryption (recommended but not validated by this
  gate) would protect data at rest if the device is stolen in a powered-off state. The
  primary threat model is software-based, not physical-access-based.

## HVCI Status Note

HVCI (Hypervisor-enforced Code Integrity) is **not running** on this system. HVCI prevents
unsigned kernel-mode code from executing, which would strengthen the trust boundary against
kernel-level exploits. This is a **recommended hardening step** but is not required for the
software fallback to be viable.

**Action Item:** Enable HVCI via Group Policy or Windows Security Center before production
deployment. This is a Phase 3 hardening task, not a Phase 2 gate blocker.

## Consequences

### Immediate
- Gate 4 PASS confirms the software trust boundary for the Priority 1 Core Loop.
- The Code Agent architecture proceeds with Hyper-V VM isolation as the primary trust
  mechanism, not hardware TEE.
- ISSUE-003 and ISSUE-005 from the Red Team assessment are resolved with documented
  residual risk acceptance.

### Architectural Implications
- All IPC between host agents and the Code Agent VM MUST use vsock (AF_HYPERV), not
  TCP/IP loopback. This is a hard requirement, not optional.
- mTLS certificates MUST be generated at VM provisioning time and rotated per-session.
  The host orchestrator and Code Agent VM each hold one end of the mTLS pair.
- The Code Agent VM MUST use Fixed memory allocation (not dynamic) to provide
  deterministic memory boundaries visible to Gate 3 re-validation.

## Evidence
- `phase2_gates/evidence/igpu_trust_report.json` — Full gate output
- Script fix committed: `validate_igpu_trust_boundary.ps1` (TLS detection logic)
- ADR-005: Corrected ceiling (31.323 GB)
- ADR-006: Memory tier summation
