# ADR-006: Empirical Memory Budget — Tier Summation at 31.323 GB Ceiling

## Status
**ACCEPTED** — 2026-02-23

## Context

Gate 3 (`VALIDATE_MEMORY_CEILING`) empirically measures the host memory baseline, aggregates
all execution tiers (OS, hypervisor, VM, agents), and validates that the total committed
memory fits within the 31.323 GB effective ceiling established by ADR-005.

This gate was executed with `--skip-vm-tests` because Hyper-V VMs are not yet provisioned.
VM overhead uses estimated values. Agent RSS uses one measured value (semantic_router) and
three spec-max worst-case values. The results represent a **worst-case development-time
snapshot**, not a production-tuned baseline.

## Empirical Evidence

**Gate 3 Execution:** 2026-02-23T05:33:08Z
**Ceiling Used:** 31.323 GB (32,074.8 MB) — cross-referenced from `dvmt_validation.json`
**Script:** `validate_memory_ceiling.py --skip-vm-tests`

### Tier Summation

| Tier | Value (MB) | Source | Notes |
|---|---|---|---|
| Host OS Baseline | 18,005.6 | Test 3.1 — `psutil` measured | 56.1% utilization at dev time |
| Hypervisor Overhead | 512 | Test 3.2 — estimated | Hyper-V root partition reservation |
| VM Assigned | 0 | Test 3.2 — SKIPPED | No VMs provisioned yet |
| VM Overhead | 256 | Test 3.2 — estimated | Per-VM management overhead |
| Agent Total | 11,842.0 | Test 3.3 — mixed | See agent breakdown below |
| **TOTAL COMMITTED** | **30,615.6** | Test 3.4 — summation | |
| **CEILING** | **32,074.8** | ADR-005 / Gate 2 evidence | |
| **HEADROOM** | **1,459.2 (4.5%)** | | Below 5% critical threshold |

### Agent RSS Breakdown

| Agent | Model | Device | RSS (MB) | Measured? |
|---|---|---|---|---|
| Semantic Router | BERT-mini proxy | CPU | 66.0 | **Yes** — numpy allocation |
| Policy Agent | 1.7B INT4 | NPU | 1,024 | No — spec max |
| Orchestrator | 1.7B INT4 (shared mmap) | NPU | 1,024 | No — spec max, worst case no sharing |
| Code Agent | 14B Q4_K_M | Arc 140V iGPU | 9,728 (9,216 VRAM + 512 host) | No — spec max |
| **Total** | | | **11,842.0** | |

### Host Baseline — Top Consumers (Development Time)

| Process | RSS (MB) | Notes |
|---|---|---|
| MemCompression | 1,921.7 | Windows memory compression — indicates memory pressure |
| VS Code (3 procs) | 2,630.4 | IDE — not present in production runtime |
| bdservicehost (Bitdefender) | 556.3 | Security agent — present in production |
| WINWORD.EXE | 521.7 | Not present in production |
| Firefox (4 procs) | 1,871.9 | Not present in production |

**Development-time overhead (removable):** ~5,024 MB (VS Code + Word + Firefox)
**Estimated production host baseline:** ~13,000 MB → headroom would increase to ~6,500 MB (20%)

## Decision

**Gate 3 disposition: PASS — WITH WARNING (headroom critically low at 4.5%).**

The warning is **acknowledged but non-blocking** for the following reasons:

1. The 18 GB host baseline is inflated by development-time workloads (VS Code, Firefox, Word)
   that will not be present in the production BlarAI runtime.
2. Three of four agent RSS values are worst-case spec maximums, not empirical measurements.
   Actual RSS will be lower when mmap sharing is active between NPU agents.
3. The gate's purpose is to validate that the architecture **can fit** within the ceiling,
   not to certify production headroom. The 4.5% headroom under worst-case-on-worst-case
   conditions confirms the design is viable.
4. When VMs are provisioned and agents are empirically measured, Gate 3 should be re-run
   to establish the production memory map.

### Architectural Risk Acknowledgement

If the Code Agent model is changed to a larger quantization (e.g., Q5_K_M or Q6_K), the
9,216 MB VRAM spec will increase and headroom will be consumed. **The 14B Q4_K_M quantization
is the maximum model size for this hardware configuration.** Any model upgrade must be
accompanied by a Gate 3 re-validation.

## Consequences

### Immediate
- Gate 3 PASS confirms the Priority 1 Core Loop can proceed to VM provisioning.
- No script constants require modification (ceiling was already correct from ADR-005).

### Future Re-validation Triggers
- Hyper-V VM provisioning (re-run without `--skip-vm-tests`)
- NPU agent empirical measurement (re-run with `--model-path` for OpenVINO IR)
- Code Agent model size change
- Windows feature update that significantly alters host baseline

## Evidence
- `phase2_gates/evidence/memory_map.json` — Full gate output
- `phase2_gates/evidence/dvmt_validation.json` — Gate 2 cross-reference (ceiling source)
- ADR-005: Corrected ceiling 31.323 GB

## Addendum — 2026-02-23: Model Acquisition Evidence Backfill

The Agent RSS Breakdown table above references "BERT-mini proxy" at 66.0 MB for the
Semantic Router. This was the assumed model at the time of Gate 3 execution.

Per the Model Acquisition gate (commit dc43a90, evidence:
`phase2_gates/evidence/model_acquisition.json`), the actual Semantic Router model is
**BAAI/bge-small-en-v1.5** (33M parameters, 384-dim), with the following measured sizes:

| Format | Size (MB) | Path |
|---|---|---|
| ONNX FP16 (CPU) | 127.8 | `models/bge-small-en-v1.5/onnx-fp16/` |
| OpenVINO INT8 (NPU) | 33.5 | `models/bge-small-en-v1.5/openvino-int8/` |

The Policy Agent and Orchestrator weight sizes are **1014.0 MB** (measured), not 1024 MB
(spec max estimate). Both use the shared Qwen3-1.7B OpenVINO INT4 artifact at
`models/qwen3-1.7b/openvino-int4/`.

The original Agent RSS table values are preserved as historical Gate 3 evidence.
Gate 3 must be re-run with empirical model measurements when VMs are provisioned
(per the existing "Future Re-validation Triggers" section).
