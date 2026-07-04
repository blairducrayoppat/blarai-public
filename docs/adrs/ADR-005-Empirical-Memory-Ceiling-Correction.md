# ADR-005: Empirical Memory Ceiling Correction — 31.323 GB

## Status
**ACCEPTED** — 2026-02-23

## Context

The Phase 1 architectural baseline (`Use Cases_FINAL.md`, ISSUE-001 resolution) defined a
hard memory ceiling of **31.5 GB**, computed as:

```
32 GB (raw LPDDR5X-8533) − 512 MB (DVMT BIOS Pre-Allocation) = 31.5 GB
```

This assumption was based on the Intel specification for a 512 MB DVMT pre-allocation on
Lunar Lake SoCs. Phase 2 Gate 2 (`VALIDATE_DVMT_BUDGET`) was designed to empirically
validate this assumption.

## Empirical Evidence

**Gate 2 Execution:** 2026-02-23T05:12:54Z  
**Hardware:** ASUS ExpertBook P5 (P5405CSA), BIOS P5405CSA.328  
**Processor:** Intel Core Ultra 7 258V (Lunar Lake)  
**GPU:** Intel Arc 140V GPU (16GB designation — shared memory capable)  

| Measurement | Value | Source |
|---|---|---|
| Raw Physical (spec) | 32,768 MB (32 GB) | Architecture baseline |
| OS-Visible via WMI | 32,075.2 MB (31.323 GB) | `Win32_ComputerSystem.TotalPhysicalMemory` |
| Total Firmware Reservation | **692.8 MB (~693 MB)** | 32,768 − 32,075.2 |
| Intel iGPU AdapterRAM (WMI) | 2,048 MB | `Win32_VideoController.AdapterRAM` |
| Registry DVMT values | `null` (not exposed) | Display adapter class registry |
| BIOS DVMT registry split | Not determinable | Intel driver does not publish discrete DVMT value |

### Reservation Decomposition (Estimated)

The 693 MB total firmware reservation includes:

| Component | Estimated Range | Notes |
|---|---|---|
| DVMT Pre-Allocation | 512–640 MB | Primary iGPU reservation |
| Intel CSME (Management Engine) | 32–64 MB | Converged Security & Management Engine |
| Platform Trust / VT-d | 16–48 MB | IOMMU, PTT firmware regions |
| BIOS/UEFI runtime services | 8–32 MB | EFI runtime memory map entries |

**Total estimated:** 568–784 MB. The measured 693 MB falls within this range.

## Decision

**Correct the architectural memory ceiling from 31.5 GB to 31.323 GB.**

Rationale:
1. The empirical measurement (31.323 GB) is the physical truth reported by the OS.
2. The 177 MB reduction represents **0.55%** of the total memory budget.
3. The WMI `TotalPhysicalMemory` is the authoritative source for OS-visible memory —
   all VM sizing, agent RSS budgets, and memory tier calculations operate within this
   boundary.
4. The discrepancy does NOT change the architectural design. It tightens headroom by
   a non-material amount.

## Consequences

### Upstream (Architectural Baseline)
- `Use Cases_FINAL.md` ISSUE-001 resolution text references "31.5 GB". This remains
  valid as the *designed* ceiling. The empirical correction is documented here and in
  the gate evidence, not retroactively patched into Phase 1 artifacts.

### Downstream (Phase 2+ Implementation)
- **All measurement scripts** updated to use `EFFECTIVE_CEILING_GB = 31.323`
- **Gate 3 (VALIDATE_MEMORY_CEILING)** will cross-reference `dvmt_validation.json`
  and automatically use the empirical 31.323 GB value.
- **VM sizing** must use 31.323 GB as the hard ceiling for Hyper-V memory allocation.
- **Code Agent (14B Q4_K_M)** VRAM budget unchanged — iGPU uses shared system memory,
  and the 177 MB reduction is absorbed by the OS/hypervisor tier, not the agent tier.

### Gate 2 Disposition
- Gate 2 formal disposition: **FAIL** (script output — tolerance exceeded)
- Gate 2 architectural disposition: **PASS WITH CORRECTION** (Lead Architect ruling)
- The failure was a detection success — the gate performed exactly as designed by
  identifying a deviation from assumption. The corrected value is now canonical.

## Evidence
- `phase2_gates/evidence/dvmt_validation.json` — Full gate output
- Hardware snapshot in evidence confirms: Intel Core Ultra 7 258V, ASUS P5405CSA,
  BIOS P5405CSA.328, Windows 11 Pro Build 26200
