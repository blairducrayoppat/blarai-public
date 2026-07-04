# Phase 2: Empirical Hardware Validation — Gate Execution Test Plan

**Version:** 1.1  
**Date:** 2026-02-23  
**Author:** Copilot Agent (Principal Engineer)  
**Prerequisite:** Phase 1 Architectural Baseline locked (`Use Cases_FINAL.md`, 9 Red Team Issues RESOLVED)  
**Target Hardware:** ASUS ExpertBook P5 — Intel Core Ultra 7 258V (Lunar Lake), 32GB LPDDR5X-8533, Arc 140V (Xe2) iGPU, Intel AI Boost NPU (48 TOPS)  
**Hard Ceiling:** ~~31.5GB~~ **31.323GB** effective (32GB physical − **693MB** empirical DVMT reservation)  
**Ceiling Revision:** Gate 2 empirical evidence (2026-02-23) shows inferred DVMT = 692.8MB, not the assumed 512MB. See `phase2_gates/evidence/dvmt_validation.json`.

---

## Preamble

This document defines the **exact test procedures**, **metrics to extract**, and **strict Pass/Fail decision trees** for the four mandatory hardware validation gates that must complete **before any agent implementation code is written**. These gates are the empirical foundation upon which all memory allocations, scheduling priorities, and execution tier definitions depend.

All gates run on the **physical Lunar Lake hardware**. No emulation, no simulation, no estimation. Failure of any gate triggers a documented escalation to the Lead Architect — not automatic mitigation.

---

## Gate 1: VALIDATE_NPU_SCHEDULING

**Red Team Issue:** ISSUE-002  
**Affected Use Cases:** [001], [002], [004]  
**Objective:** Empirically characterize the Intel NPU's concurrent scheduling behavior to determine whether the dual-model architecture (Policy Agent 1.7B INT4 + Orchestrator 1.7B INT4) is feasible within defined latency budgets.

### Test Procedure

#### Test 1.1 — Single-Model Baseline (Policy Agent Proxy)

1. Load a single 1.7B INT4 ONNX model onto the NPU via OpenVINO Runtime (candidate: `openvino.runtime.Core`).
2. Run 100 inference iterations with a fixed 512-token input sequence (synthetic prompt, deterministic seed).
3. Record per-inference latency (wall-clock time, `time.perf_counter_ns()`).
4. Record peak RSS of the inference process via `psutil.Process.memory_info().rss`.
5. Record NPU utilization if available via `openvino.runtime` profiling or Intel NPU driver telemetry.

**Metrics Captured:**
| Metric | Unit | Collection Method |
|--------|------|-------------------|
| P50 inference latency | ms | Sorted latency array, index 50 |
| P95 inference latency | ms | Sorted latency array, index 95 |
| P99 inference latency | ms | Sorted latency array, index 99 |
| Mean inference latency | ms | Arithmetic mean |
| Peak RSS | MB | `psutil` |
| NPU utilization | % (if available) | OpenVINO profiling API |

#### Test 1.2 — Single-Model Baseline (Orchestrator Proxy)

Identical to Test 1.1 but with a 1024-token input sequence (simulating conversational context).

#### Test 1.3 — Dual-Model Concurrent Load

1. Load **both** 1.7B INT4 models onto the NPU simultaneously via separate OpenVINO `InferRequest` handles from a single process (shared `Core` instance).
2. From two threads, submit inference requests concurrently:
   - Thread A (Policy Agent proxy): 100 iterations, 512-token input, back-to-back.
   - Thread B (Orchestrator proxy): 100 iterations, 1024-token input, back-to-back.
3. Record per-inference latency for each thread independently.
4. Record total wall-clock time for both threads to complete all 100 iterations.
5. Record peak RSS of the combined process.

**Metrics Captured:**
| Metric | Unit | Collection Method |
|--------|------|-------------------|
| Policy Agent proxy — P50/P95/P99 latency | ms | Per-thread latency array |
| Orchestrator proxy — P50/P95/P99 latency | ms | Per-thread latency array |
| Scheduling mode observed | parallel / time-sliced | Compare sum-of-baselines vs actual total time |
| Peak combined RSS | MB | `psutil` |
| Throughput ratio | % of single-model | (single-model throughput / concurrent throughput) × 100 |

#### Test 1.4 — Preemption Latency Measurement

1. Start the Orchestrator proxy on a background thread generating tokens continuously (simulating mid-generation).
2. From the main thread, inject a Policy Agent proxy inference request at a random point during Orchestrator generation (using `threading.Event`).
3. Measure the wall-clock time from Policy Agent inference submission to Policy Agent inference completion — this is the **preemption latency**.
4. Repeat 50 times with randomized injection points.

**Metrics Captured:**
| Metric | Unit | Target |
|--------|------|--------|
| Preemption P50 latency | ms | ≤ 200 |
| Preemption P95 latency | ms | ≤ 200 |
| Preemption P99 latency | ms | ≤ 500 |
| Orchestrator resume latency (time from Policy Agent completion to Orchestrator next token) | ms | ≤ 500 |

#### Test 1.5 — KV-Cache Persistence Across Context Switch

1. Load the Policy Agent proxy model, run 10 inference iterations to warm KV-cache.
2. Record the generation output tokens for iteration 11 (warm state).
3. Load the Orchestrator proxy model on the NPU (triggering potential context switch).
4. Run 10 Orchestrator inferences.
5. Switch back to the Policy Agent proxy model.
6. Run inference with the same input as iteration 11.
7. Compare output tokens: if identical to warm-state iteration 11, KV-cache persisted. If different, KV-cache was evicted.

**Metrics Captured:**
| Metric | Expected | Fallback |
|--------|----------|----------|
| KV-cache persistence after context switch | Tokens match (PASS) | Tokens differ → measure KV-cache reconstruction latency |
| KV-cache reconstruction latency (if evicted) | N/A | Must be ≤ 500ms |

### Decision Tree

```
VALIDATE_NPU_SCHEDULING
│
├── Test 1.3: Is concurrent dual-model throughput ≥ 60% of single-model baseline?
│   ├── YES → NPU supports concurrent inference → Architecture proceeds as designed
│   │   └── Continue to Test 1.4 (preemption) and Test 1.5 (KV-cache)
│   └── NO → NPU is time-sliced
│       ├── Test 1.4: Is preemption P95 ≤ 200ms?
│       │   ├── YES → Time-sliced but within latency budget → Proceed with Priority 0/1 scheduling
│       │   └── NO → Preemption latency exceeds budget
│       │       └── ESCALATE: Consider CPU fallback for Policy Agent probabilistic classifier
│       └── Test 1.5: Does KV-cache persist?
│           ├── YES → Warm-state architecture valid
│           └── NO → Measure reconstruction latency
│               ├── ≤ 500ms → Budget for reconstruction, revise latency targets
│               └── > 500ms → ESCALATE: CPU-side KV-cache shadow copy required
│
├── ALL targets met → GATE PASS
└── ANY target missed → GATE FAIL
    └── Document failure fingerprint → Escalate to Lead Architect
        └── DO NOT delete branch. Preserve for audit.
```

**Mandatory Rollback:** If GATE FAIL, no agent implementation code is written. The NPU scheduling model must be resolved (CPU fallback architecture or revised latency budgets) before proceeding.

---

## Gate 2: VALIDATE_DVMT_BUDGET

**Red Team Issue:** ISSUE-008 (Option A — Fixed DVMT Pre-Allocation)  
**Affected Use Cases:** ALL (defines the effective memory ceiling)  
**Objective:** Empirically confirm that the BIOS-level DVMT Pre-Allocation on the physical Lunar Lake unit is exactly 512MB (the assumed minimum granularity), establishing the precise effective memory ceiling.

### Test Procedure

#### Test 2.1 — BIOS DVMT Pre-Allocation Readout

1. Boot into BIOS/UEFI setup on the ExpertBook P5.
2. Navigate to the DVMT Pre-Allocation setting under chipset/graphics configuration.
3. Record the current setting and all available options (expected: 512MB minimum).
4. **Do not change** the setting. Photograph the BIOS screen for evidence.

#### Test 2.2 — OS-Level DVMT Verification (PowerShell)

1. Query the Windows registry and WMI for GPU memory allocation:
   - `Get-CimInstance Win32_VideoController` → `AdapterRAM` property
   - Registry key: `HKLM\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0000` → `HardwareInformation.qwMemorySize`, `DedicatedVideoMemory`
2. Query total physical memory via `Get-CimInstance Win32_ComputerSystem` → `TotalPhysicalMemory`.
3. Compute: `effective_ceiling = TotalPhysicalMemory - DVMT_PreAllocation`.
4. Validate: `effective_ceiling` must equal 31.5GB (±64MB tolerance for firmware rounding).

#### Test 2.3 — Runtime Memory Visibility Validation

1. Open Task Manager → Performance → Memory.
2. Record "Hardware Reserved" value — this should include the DVMT pre-allocation.
3. Record "Total Physical Memory" visible to Windows (expected: ~31.5GB or ~31.3GB after firmware tables).
4. Cross-reference with `systeminfo | findstr "Total Physical Memory"`.

**Metrics Captured:**
| Metric | Unit | Expected Value |
|--------|------|----------------|
| BIOS DVMT Pre-Allocation | MB | 512 |
| BIOS DVMT minimum selectable | MB | 512 (confirm no lower option) |
| Windows `TotalPhysicalMemory` | GB | 31.5 (±0.2GB) |
| Windows "Hardware Reserved" | MB | ≥ 512 |
| Computed effective ceiling | GB | 31.5 (±0.2GB) |

### Decision Tree

```
VALIDATE_DVMT_BUDGET
│
├── Test 2.1: Is BIOS DVMT Pre-Allocation = 512MB?
│   ├── YES → Architectural assumption confirmed
│   └── NO
│       ├── DVMT < 512MB → Ceiling is HIGHER than assumed → Update ceiling upward → PASS (favorable)
│       └── DVMT > 512MB → Ceiling is LOWER than assumed
│           └── Recompute all memory budgets against new ceiling
│               ├── All execution tiers still fit → PASS with updated ceiling
│               └── Any execution tier exceeds new ceiling → GATE FAIL
│                   └── ESCALATE to Lead Architect: memory budget redesign required
│
├── Test 2.2 + 2.3: Does OS-visible memory = 32GB - DVMT (±0.2GB)?
│   ├── YES → Cross-validated → GATE PASS
│   └── NO → Unexplained memory reservation detected
│       └── Investigate: firmware tables, Intel ME reservation, other BIOS allocations
│           └── Document all reservations → Recompute effective ceiling
│               └── Re-evaluate execution tiers against actual ceiling
│
├── ALL validations consistent → GATE PASS (effective ceiling confirmed)
└── ANY inconsistency → GATE FAIL
    └── Document failure fingerprint → Preserve branch → Escalate
```

**Mandatory Rollback:** If the effective ceiling is lower than 31.5GB, all downstream memory allocations (Gate 3) are recomputed against the empirically confirmed ceiling before proceeding.

---

## Gate 3: VALIDATE_MEMORY_CEILING

**Red Team Issue:** ISSUE-004  
**Affected Use Cases:** [001], [002], [004], [005]  
**Objective:** Construct a precise, empirically measured memory map of all system memory consumers on the physical Lunar Lake hardware. Validate that the Priority 1 Core Loop and all defined execution tiers fit within the effective ceiling established by Gate 2.

### Test Procedure

#### Test 3.1 — Windows + Hyper-V Root Partition Baseline

1. Boot Windows 11 Pro normally (no AI agent VMs running).
2. Enable Hyper-V role (if not already enabled).
3. Record baseline memory consumption:
   - Total committed memory via `Get-CimInstance Win32_OperatingSystem` → `TotalVisibleMemorySize`, `FreePhysicalMemory`
   - `(Get-Process) | Measure-Object WorkingSet64 -Sum` → total process working set
   - Hyper-V root partition overhead via Performance Monitor: `\Hyper-V Hypervisor Root Partition\*`
4. Record with **zero VMs running** (Hyper-V idle baseline).

#### Test 3.2 — Single TDX-Candidate VM Overhead

1. Create a minimal Linux guest VM (Alpine Linux or similar, ≤256MB configured RAM).
2. Boot the VM.
3. Measure host-side memory increase: delta between pre-VM and post-VM committed memory.
4. Record inside-guest memory: `free -m` inside the VM.
5. Compute per-VM overhead: `host_delta - guest_configured_RAM` = Hyper-V structural overhead (EPT, IOMMU, virtio, metadata).
6. Repeat with 2, 3, and 4 concurrent minimal VMs to characterize per-VM marginal overhead.

**Metrics Captured:**
| Metric | Unit | Expected Range |
|--------|------|----------------|
| Windows + Hyper-V idle baseline | GB | 6–8 |
| Windows + Hyper-V under TDX workload | GB | 8–10 |
| Per-VM structural overhead (host-side, beyond configured RAM) | MB | 256–512 |
| Per-VM guest OS footprint (inside guest) | MB | 128–512 |

#### Test 3.3 — Agent RSS Measurement Under Load

For each agent component (simulated with representative workloads):

1. **Policy Agent Proxy:** Load 1.7B INT4 model on NPU. Run 100 inferences. Record peak RSS.
   - Include: KV-cache (target 350–550MB), deterministic rule engine placeholder (~50MB), mTLS state placeholder (~5MB).

2. **Orchestrator Proxy:** Load 1.7B INT4 model on NPU. Run 100 inferences with 1024-token context. Record peak RSS.
   - Include: KV-cache (target 300–500MB).

3. **Semantic Router Proxy:** Load BAAI/bge-small-en-v1.5 (33M params, 384-dim) on CPU (ONNX Runtime, FP16). Run 500 classifications. Record peak RSS.
   - Expected: 128–200MB (measured ONNX FP16 artifact: 127.8 MB, see `phase2_gates/evidence/model_acquisition.json`).

4. **Shared mmap Weight File:** Measure the actual RSS contribution of a single 1.7B INT4 weight file mapped via `mmap`. Confirm zero-copy semantics (only one copy in physical RAM despite two processes mapping the same file).

5. **Substrate Proxy (Priority 2):** Load HNSW index (50K synthetic vectors, 384-dim) + BM25 index + 384-dim sentence transformer INT8 on NPU. Record peak RSS during concurrent query load.

**Metrics Captured (per component):**
| Component | Metric | Unit | Budget |
|-----------|--------|------|--------|
| Policy Agent | Peak RSS (total) | MB | ≤ 2500 (with guest OS) |
| Policy Agent | KV-cache measured | MB | 350–550 |
| Policy Agent | Deterministic engine | MB | ≤ 50 |
| Orchestrator | Peak RSS (total) | MB | ≤ 1800 (with guest OS) |
| Orchestrator | KV-cache measured | MB | 300–500 |
| Semantic Router | Peak RSS (total) | MB | ≤ 150 |
| Shared mmap weights | Physical pages (single copy) | MB | ~1000 |
| Substrate | Peak RSS (total) | MB | ≤ 3000 |

#### Test 3.4 — Execution Tier Summation and Validation

Using empirical data from Tests 3.1–3.3, compute total memory for each execution tier:

**Tier 1 — Conversational (Priority 1 + 2, no Code Agent):**
```
Total_Tier1 = Windows_Hyper-V_Base
            + (N_VMs × Per_VM_Overhead)
            + Policy_Agent_RSS
            + Orchestrator_RSS
            + Semantic_Router_RSS
            + Shared_mmap_Weights
            + Substrate_RSS
```

**Tier 2 — Code Agent Active (Priority 1 + degraded Priority 2 + Code Agent [005]):**
```
Total_Tier2 = Windows_Hyper-V_Base
            + (N_VMs × Per_VM_Overhead)
            + Policy_Agent_RSS        # NEVER degraded
            + Orchestrator_RSS_Degraded  # KV-cache flushed
            + Semantic_Router_RSS
            + Shared_mmap_Weights
            + Substrate_RSS_Degraded     # Cross-encoder suspended
            + Code_Agent_RSS             # 12–14GB estimated
```

**Pass Criteria:**
- `Total_Tier1 ≤ Effective_Ceiling` (from Gate 2)
- `Total_Tier2 ≤ Effective_Ceiling` (from Gate 2)
- `Policy_Agent_RSS` is the **first** allocation confirmed feasible
- Remaining headroom ≥ 1GB in Tier 1 (safety margin for OS working set fluctuation)

### Decision Tree

```
VALIDATE_MEMORY_CEILING
│
├── Test 3.4 Tier 1: Total_Tier1 ≤ Effective_Ceiling?
│   ├── YES → Tier 1 fits
│   │   ├── Headroom ≥ 1GB? → TIER 1 PASS
│   │   └── Headroom < 1GB → WARNING: tight margin, require Lead Architect sign-off
│   └── NO → TIER 1 FAIL
│       └── ESCALATE: Priority 1 Core Loop exceeds ceiling at baseline
│           └── Candidate resolutions: reduce Substrate footprint, Lenovo Y700 offload
│
├── Test 3.4 Tier 2: Total_Tier2 ≤ Effective_Ceiling?
│   ├── YES → Tier 2 fits → TIER 2 PASS
│   └── NO → TIER 2 FAIL
│       └── ESCALATE: Code Agent coexistence exceeds ceiling
│           └── Candidate resolutions: reduce Code Agent model (7B), increase degradation
│
├── BOTH tiers PASS → GATE PASS
│   └── Deliverable: Publish empirical memory map with exact static VM limits
└── ANY tier FAIL → GATE FAIL
    └── Document all measurements → Preserve branch → Escalate to Lead Architect
```

**Mandatory Rollback:** If GATE FAIL, no VM memory limits are committed. The memory map is preserved as a diagnostic artifact. The architecture must be revised to fit within the empirical ceiling before implementation.

---

## Gate 4: VALIDATE_IGPU_TRUST_BOUNDARY

**Red Team Issue:** ISSUE-008  
**Affected Use Cases:** [005], [006]  
**Objective:** Binary go/no-go determination of TDX Connect (TDISP) support on the physical Lunar Lake SoC's integrated Arc 140V GPU. This gate determines whether [005] operates with full GPU trust boundary or under a reduced threat model, and whether [006] can use the iGPU at all.

### Test Procedure

#### Test 4.1 — TDX Base Support Verification

1. Verify TDX is enabled in BIOS (Intel Trusted Execution Technology settings).
2. From Windows, query TDX support:
   - `CPUID` leaf `0x21` (Intel TDX enumeration) — record output.
   - `Get-CimInstance -Namespace root\virtualization\v2 -ClassName Msvm_SecurityService` (Hyper-V security capabilities).
3. Verify Hyper-V can launch a TDX-enabled (Confidential) VM:
   - `Set-VMSecurity -VMName <test_vm> -EncryptStateAndVmMigrationTraffic $true`
   - Attempt VM boot → record success/failure.

#### Test 4.2 — TDX Connect / TDISP Enumeration

1. Check for TDISP capability on the iGPU PCIe/internal bus topology:
   - `wmic path Win32_PnPEntity where "Name like '%Arc%'" get DeviceID, Name` — identify iGPU device path.
   - Query PCIe extended capabilities for TDISP support via device manager or Intel diagnostic tools.
   - Check Intel GPU driver version and release notes for TEE-IO / TDX Connect support declarations.
2. Attempt to configure a TDX-enabled VM with GPU passthrough / GPU-PV:
   - `Add-VMGpuPartitionAdapter -VMName <test_vm>` (GPU-PV for Arc 140V)
   - If TDX Connect is available, the GPU partition should operate within the TD's encrypted memory boundary.
   - Record whether GPU memory operations from within the TD are encrypted (observable via attestation report or Intel documentation).
3. Query attestation report from within the TD guest:
   - If TDX Connect active, the attestation report should include the GPU as a trusted device.
   - Record attestation report fields.

#### Test 4.3 — Fallback Posture Validation (If TDISP Unavailable)

If Test 4.2 determines TDISP is unavailable:

1. Verify [005] can operate on iGPU **without** TDX Connect (standard GPU-PV):
   - Load 14B Q4_K_M model via Vulkan/oneAPI on Arc 140V.
   - Run inference within a standard (non-confidential) VM.
   - Record peak VRAM usage, inference throughput (tokens/sec).
2. Verify [005] compensating controls are active:
   - Policy Agent AAB blocks any tool call extracting GPU memory contents (simulate via synthetic CAR with GPU-memory-read intent → verify rejection).
   - Zero-outbound-network enforcement verified (attempt network egress from Code Agent VM → verify block at both vsock/Policy Agent and Ubiquiti router level).
3. Document [006] prohibition: Record that [006] is architecturally prohibited from iGPU when TDISP is unavailable. Verify CPU-only inference path exists (ONNX Runtime CPU with 9B–14B Q4_K_M model → record throughput).

**Metrics Captured:**
| Metric | Unit | Expected |
|--------|------|----------|
| TDX base support | boolean | TRUE |
| TDX Connect / TDISP support for iGPU | boolean | UNKNOWN (to be determined) |
| GPU-PV available for Arc 140V | boolean | TRUE |
| Attestation report includes GPU | boolean | Depends on TDISP |
| [005] iGPU inference throughput (tokens/sec) | tok/s | ≥ 8 |
| [005] peak VRAM usage | GB | 8–10 |
| [006] CPU-only inference throughput (if TDISP unavailable) | tok/s | ≥ 2 (estimated) |

### Decision Tree

```
VALIDATE_IGPU_TRUST_BOUNDARY
│
├── Test 4.1: Is TDX base support available and functional?
│   ├── YES → Continue to Test 4.2
│   └── NO → CRITICAL FAILURE
│       └── ESCALATE IMMEDIATELY: TDX is foundational to ALL isolation claims
│           └── Architecture requires fundamental redesign
│
├── Test 4.2: Is TDX Connect (TDISP) available for iGPU?
│   ├── YES → Full trust boundary available
│   │   ├── [005] operates on iGPU with full TEE-IO → PASS
│   │   ├── [006] operates on iGPU with full TEE-IO → PASS
│   │   └── GATE PASS (full posture)
│   └── NO → TDISP unavailable → Reduced posture
│       ├── [005] operates on iGPU under reduced threat model
│       │   └── Source code = regenerable/rotatable → PASS (reduced, documented)
│       ├── [006] PROHIBITED from iGPU → CPU-only fallback
│       │   └── Test 4.3: CPU-only throughput acceptable? 
│       │       ├── ≥ 2 tok/s → PASS (degraded performance accepted)
│       │       └── < 2 tok/s → WARNING: [006] operationally marginal
│       │           └── Lead Architect decision: accept or defer [006]
│       └── GATE PASS (reduced posture, documented)
│
└── GATE outcome determines [005] and [006] operational security posture
    └── Publish in security attestation report
```

**Mandatory Rollback:** If TDX base support is absent, the entire isolation architecture is invalidated. All work halts pending Lead Architect redesign decision. If only TDISP is absent, the reduced posture is documented and [006] is limited to CPU-only — no code deletion occurs.

---

## Execution Order

The four gates execute in the following strict order:

| Order | Gate | Dependency | Rationale |
|-------|------|------------|-----------|
| 1 | VALIDATE_DVMT_BUDGET | None | Establishes the effective memory ceiling used by all subsequent gates |
| 2 | VALIDATE_NPU_SCHEDULING | None (parallel with Gate 1) | Can run independently; determines compute allocation |
| 3 | VALIDATE_MEMORY_CEILING | Gate 1 (ceiling value) | Requires the confirmed ceiling from DVMT; requires NPU RSS data from Gate 2 |
| 4 | VALIDATE_IGPU_TRUST_BOUNDARY | None (parallel with Gates 1–2) | Binary go/no-go; independent of memory/NPU |

**Gates 1, 2, and 4 may execute in parallel.** Gate 3 is sequentially dependent on Gate 1 (effective ceiling) and partially on Gate 2 (NPU RSS measurements feed into the memory map).

---

## Deliverables

Upon completion of all four gates:

1. **Empirical Memory Map** (`phase2_gates/evidence/memory_map.json`) — precise measurements of every memory consumer with actual values, not estimates.
2. **NPU Scheduling Report** (`phase2_gates/evidence/npu_scheduling_report.json`) — concurrent throughput, preemption latency, KV-cache persistence results.
3. **DVMT Confirmation** (`phase2_gates/evidence/dvmt_validation.json`) — BIOS setting, OS-visible memory, computed ceiling.
4. **iGPU Trust Boundary Report** (`phase2_gates/evidence/igpu_trust_report.json`) — TDX base status, TDISP status, [005]/[006] operational posture.
5. **Static VM Memory Limits** (`phase2_gates/evidence/vm_memory_limits.json`) — exact per-VM memory allocations derived from the empirical map.
6. **Gate Summary** (`phase2_gates/evidence/gate_summary.md`) — PASS/FAIL for each gate with disposition.

---

## Failure Fingerprinting

Every gate failure produces a structured failure record:

```json
{
  "gate": "VALIDATE_<GATE_NAME>",
  "timestamp": "ISO-8601",
  "test_id": "Test X.Y",
  "metric": "<metric_name>",
  "expected": "<value or range>",
  "actual": "<measured value>",
  "disposition": "FAIL | WARNING",
  "escalation": "Lead Architect decision required",
  "branch_preserved": "feature/phase2-scaffolding",
  "evidence_path": "phase2_gates/evidence/<artifact>"
}
```

Failed branches are **never deleted**. All measurements are preserved for audit regardless of pass/fail outcome.
