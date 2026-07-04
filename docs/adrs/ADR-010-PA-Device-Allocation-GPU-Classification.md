# ADR-010: Policy Agent Device Allocation — GPU Classification

**Status:** ACCEPTED (Partially superseded — see ADR-011)  
**Date:** 2026-02-24  
**Author:** Lead Architect + Copilot Agent (Claude Opus 4.6)  
**Supersedes:** USE-CASE-001 §NPU Priority 0 (partial), ADR-008 §4.1  
**Partially Superseded By:** ADR-011 (2026-02-27) — AO also moved to GPU; NPU retired from P1 Core Loop. PA-on-GPU finding in this ADR remains valid.  
**Branch:** `feature/p1-uat1-launcher`

---

## 1. Context

USE-CASE-001 specifies that the Policy Agent holds "exclusive NPU Priority 0
scheduling designation" — its inference requests preempt all other NPU workloads.
This was designed to ensure the security gate is never starved by lower-priority
inference tasks (Orchestrator at Priority 1, Substrate at Priority 2).

Phase 2 hardware validation (ADR-008) confirmed the NPU scheduling model using
proxy models: true parallel dual-model inference, KV-cache persistence across
context switches, and 0.814ms preemption P99.

However, when running the production model (Qwen2.5-1.5B-Instruct INT4-MIXED,
975.6 MB) on the actual NPU, empirical latency benchmarking revealed that the
NPU cannot meet the PA adjudication latency budget:

| Configuration | Device | Mean | P95 | P99 | Budget | Status |
|--------------|--------|------|-----|-----|--------|--------|
| Baseline (no hints, tokens=32) | NPU | 680ms | 791ms | 793ms | 230ms | 2.96x OVER |
| GENERATE_HINT=BEST_PERF | NPU | 697ms | 816ms | 817ms | 230ms | 3.06x OVER |
| max_new_tokens=8 | NPU | 577ms | 674ms | 675ms | 230ms | 2.51x OVER |
| max_new_tokens=4 | NPU | 568ms | 665ms | 665ms | 230ms | 2.43x OVER |
| PREFILL_ATTENTION=PYRAMID | NPU | 580ms | 736ms | 751ms | 230ms | 2.69x OVER |
| All NPU hints combined | NPU | 543ms | 646ms | 703ms | 230ms | 2.36x OVER |
| **GPU baseline (tokens=32)** | **GPU** | **78ms** | **125ms** | **144ms** | **230ms** | **✅ 0.54x UNDER** |
| **GPU optimized (tokens=8)** | **GPU** | **80ms** | **111ms** | **137ms** | **230ms** | **✅ 0.48x UNDER** |

All NPU optimization knobs (GENERATE_HINT, NPUW_LLM_PREFILL_ATTENTION_HINT,
NPU_COMPILER_TYPE, max_new_tokens reduction) were exhausted. The NPU latency
floor is \~430ms minimum, \~540ms mean — the bottleneck is prefill-phase
processing on the 1.5B-parameter model. This is a hardware throughput limit,
not an optimization gap.

Evidence: `phase2_gates/evidence/npu_latency_benchmark.json`

---

## 2. Decision

**Policy Agent classification runs on the Intel Arc 140V (Xe2) iGPU.**
**Orchestrator token generation remains on the Intel AI Boost NPU.**

Device allocation:

| Service | Device | Priority | Rationale |
|---------|--------|----------|-----------|
| Policy Agent (M2) | GPU (Arc 140V) | N/A (sole LLM consumer on GPU) | 78ms mean, 125ms P95, meets 230ms budget with 46% headroom |
| Orchestrator (M3) | NPU (AI Boost) | Sole consumer | 659ms acceptable for first-token (budget: 1000ms warm) |
| Semantic Router (M1) | CPU | N/A | Sub-80ms BGE embedding, no GPU/NPU needed |
| Substrate Bi-encoder (M4) | NPU (future) | Priority 2 | Deferred to later use cases |

---

## 3. Consequences

### 3.1 What Changes

1. **NPU Priority 0 preemption model is retired for PA.** PA no longer runs on
   NPU, so the Priority 0/1 scheduling relationship with Orchestrator is moot.
   PA and Orchestrator now run on separate devices — no contention to arbitrate.

2. **PA source code renamed:** `npu_inference.py` → `gpu_inference.py`.
   Class `PolicyNPUInference` → `PolicyGPUInference`.
   Result type `NPUClassificationResult` → `GPUClassificationResult`.

3. **PA config:** `device = "NPU"` → `device = "GPU"` in default.toml.
   Priority config removed (GPU has no equivalent priority mechanism).

4. **Orchestrator simplification:** Orchestrator NPU has no contention from PA.
   Preemption detection logic becomes monitoring-only (no functional impact).
   Priority remains Priority 1 for future Substrate (M4) coexistence.

5. **Shared constants:** `NPU_PA_PRIORITY` deprecated. New `PA_DEVICE` constant
   added. `PA_OV_PATH` unchanged (same model weights compile for both devices).

### 3.2 What Does NOT Change

1. **Fail-Closed architecture.** GPU inference timeout → DENY. Same guarantee.
2. **Weight integrity verification.** SHA-256 on source `.bin` file. Device-agnostic.
3. **mTLS on vsock.** Unrelated to inference device.
4. **Agentic JWT lifecycle.** Unrelated to inference device.
5. **Measured Boot Sequence.** PA still boots first, establishes CA.
6. **Action Authorization Boundary (AAB).** JWT still required for every tool-call.
7. **Epoch-based revocation.** Unrelated to inference device.
8. **Model weights on disk.** Same INT4-MIXED model compiles for both GPU and NPU.
   The path `models/qwen2.5-1.5b-instruct/openvino-int4-npu/` is retained as-is
   (the `-npu` suffix reflects INT4-MIXED quantization optimized for NPU export,
   but OpenVINO compiles it correctly for any device).

### 3.3 Residual Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| GPU contention from Windows DWM | LOW | PA classification is 78ms burst; DWM compositing is lightweight; fail-closed timeout catches stalls |
| No hardware scheduling priority for PA on GPU | MEDIUM | No contention to arbitrate — PA is sole LLM consumer on GPU; Orchestrator is on NPU |
| Shared LPDDR5X pressure from GPU allocation | LOW | GPU weights (\~1GB compiled) already counted against 31.323GB ceiling; comparable to NPU allocation |

### 3.4 ADR-008 Applicability

ADR-008's empirical findings remain valid for NPU-only workloads:
- Parallel dual-model inference → applies to Orchestrator + future Substrate
- KV-cache persistence → applies to Orchestrator context switches
- Preemption latency → applies to Orchestrator ↔ Substrate scheduling

The PA-specific findings in ADR-008 §4.1 (Priority 0 preemption of Priority 1)
are superseded — PA is no longer on NPU, so it cannot preempt or be preempted.

---

## 4. Evidence

- Benchmark script: `scripts/benchmark_npu_latency.py`
- Benchmark results: `phase2_gates/evidence/npu_latency_benchmark.json`
- NPU smoke test: `docs/NPU_SMOKE_TEST_REPORT.md`
- ADR-008 (NPU scheduling): `docs/adrs/ADR-008-NPU-Concurrent-Scheduling-Characterization.md`
