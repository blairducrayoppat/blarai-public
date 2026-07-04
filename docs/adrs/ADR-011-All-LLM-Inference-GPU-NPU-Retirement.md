# ADR-011: All LLM Inference on GPU — NPU Retirement for P1 Core Loop

**Status:** ACCEPTED  
**Date:** 2026-02-27  
**Author:** Lead Architect + Copilot Agent (Claude Opus 4.6)  
**Supersedes:** ADR-010 §Device Allocation Table (AO row only), ADR-008 §Architectural Implications (LLM rows)  
**Branch:** `feature/p5-feasibility-005-unified-model`

---

## 1. Context

ADR-010 (2026-02-24) moved the Policy Agent from NPU to GPU based on empirical
latency evidence: NPU could not meet the 230ms PA adjudication budget (543ms mean
vs GPU 78ms mean). The Orchestrator remained on NPU as the sole LLM consumer.

Subsequent feasibility studies produced cumulative evidence that the NPU is not
viable for any LLM inference workload in this system:

| Study | Finding | Evidence |
|-------|---------|----------|
| P5-001 | Context window DO-NOT-EXPAND — NPU constraints contributed | `p5_input_length_latency_matrix.json` |
| P5-003 | NPU runtime ceiling — stateful `MAX_PROMPT_LEN` failures | `p5_runtime_ceiling_matrix.json` |
| P5-004 | GPU 36–53 tps vs NPU 3–14 tps (4–5× faster) | `p5_multi_device_capability_matrix.json` |
| P5-004 | HYBRID_NPU_GPU recommendation → all-GPU inference | `FEASIBILITY_MULTI_DEVICE_CAPABILITY.md` |

Additionally, the NPU compatibility constraint forced the selection of
Qwen2.5-1.5B-Instruct as the production model. Qwen3's thinking mode produced
garbled output on NPU (pre-filled think tags, 2/3 classification accuracy).
Removing the NPU constraint reopens model selection to larger, higher-quality
models from across the Qwen3 family and beyond.

P5-005/005a are actively investigating Qwen3-8B and Qwen3-14B as unified target
models with speculative decoding (Qwen3-0.6B or Qwen3-1.7B as draft). These
models are only viable on the GPU — they cannot run on the NPU due to size,
latency, and compatibility limitations.

---

## 2. Decision

**All LLM inference (Policy Agent + Assistant Orchestrator) runs on the Intel
Arc 140V (Xe2) iGPU. The NPU is retired from the P1 Core Loop inference
pipeline.**

### 2.1 Locked Device Allocation

| Service | Device | Rationale |
|---------|--------|-----------|
| Semantic Router (M1) | CPU | BGE-small-en-v1.5 embedding, sub-80ms, no accelerator needed |
| Policy Agent (M2) | GPU (Arc 140V) | ADR-010 finding preserved; GPU meets 230ms budget with 46% headroom |
| Assistant Orchestrator (M3) | GPU (Arc 140V) | NPU retired; GPU 4–5× faster; enables larger model selection |
| Substrate Bi-encoder (M4) | TBD (future use cases) | Deferred — NPU remains a candidate for non-LLM workloads |

### 2.2 Model Selection Status — RESOLVED (ADR-012)

**Superseded by ADR-012 (2026-02-28).** Model selection is no longer PENDING.
Qwen3-14B (INT4, GPU) confirmed as target model for PA, AO, and USE-CASE-005
with speculative decoding. Configuration optimization in progress — see ADR-012 §2.2.

| Parameter | Previous (ADR-010) | ADR-011 (2026-02-27) | ADR-012 (2026-02-28) |
|-----------|-------------------|----------------------|----------------------|
| PA model | Qwen2.5-1.5B-Instruct INT4-MIXED | PENDING | **Qwen3-14B INT4** |
| AO model | Qwen2.5-1.5B-Instruct INT4-MIXED | PENDING | **Qwen3-14B INT4** |
| Model family | Qwen2.5 (NPU-compatible) | Qwen3 (preferred) | **Qwen3 (locked)** |
| Max model size | ~1.5B (NPU limit) | ~14B (GPU budget) | **14B (confirmed)** |
| Quantization | INT4-MIXED (NPU-optimized) | INT4 symmetric (GPU) | **INT4 symmetric (locked)** |
| Draft model | N/A | TBD (Qwen3-0.6B/1.7B) | **Evaluating** (see ADR-012 §2.3) |
| Speculative decoding | N/A | Candidate | **Confirmed (mandatory)** |

### 2.3 NPU Disposition

The Intel AI Boost NPU is **not decommissioned** — it remains physically present
and driver-functional. It is **deallocated** from the P1 Core Loop:

- **Not used for:** PA classification, AO generation, any LLM inference
- **Reserved for:** Future non-LLM accelerator workloads (USE-CASE-002/003
  Substrate bi-encoder, embedding offload) — subject to
  future ADRs when those use cases are implemented
- **ADR-008 empirical data:** Remains valid for NPU scheduling characterization
  but is no longer architecturally load-bearing for P1

### 2.4 Addendum — Heterogeneous Speculative Decoding (NPU as Draft Device)

**Status:** REJECTED — Task 4.2b empirical result: T-05 NPU pipeline FAILED at model compilation (LLVM ABORT)  
**Date added:** 2026-03-01  
**Resolved:** 2026-03-02 (Task 4.2b execution on branch `feature/p5-task4-2-combined-rerun`)  
**Governance gate:** Lead Architect approved evaluation scope 2026-03-01

#### Scope of Carve-Out

ADR-011 §2 retired the NPU from *full LLM inference* — PA classification and AO
generation. That ruling is unchanged. This addendum addresses a categorically
distinct allocation: the NPU serving as the **draft model device** in speculative
decoding, where:

- The draft model is 0.6B (not 14B), not used for final output
- The draft generates a proposal buffer of 3–5 tokens per step only
- Final token acceptance/rejection is performed by the GPU (14B target) exclusively
- PA security constraints are unaffected — no draft token is ever used as PA output

#### Architectural Basis

OpenVINO GenAI 2026.0 introduced headline support for heterogeneous speculative
decoding on Lunar Lake hardware. The GPU (target) and NPU (draft) share the same
LPDDR5X physical memory, enabling zero-copy token handoff via Level Zero. The
draft model runs concurrently on NPU NCE while the target model processes KV cache
on GPU — Intel's documented intended usage pattern for this SoC.

Verified API (OpenVINO GenAI 2026.0, confirmed against installed runtime):
```python
pipeline = LLMPipeline(
    target_model_path, "GPU",
    draft_model=ov_genai.draft_model(draft_npu_path, "NPU"),
    scheduler_config=scheduler,
    # Do NOT set INFERENCE_PRECISION — invalid property name on OV GenAI 2026.0 GPU device
)
```

> **NOTE (Task 4.2b, 2026-03-02):** The pipeline above was never reached. VPUX compiler aborted
> with LLVM ERROR during NPU model compilation before the Python-level LLMPipeline constructor
> completed. `INFERENCE_PRECISION` was confirmed invalid in a prior session (P5-005b).

#### Prerequisite Conditions

| Condition | Requirement | Status |
|-----------|------------|--------|
| NPU driver | ≥ 32.0.100.3104 | CONFIRMED 32.0.100.4514 — driver meets minimum but model shape incompatible with VPUX compiler |
| OpenVINO | ≥ 2026.0 | CONFIRMED installed |
| Draft model (NPU format) | `models/qwen3-0.6b/openvino-int4-npu/` | CONFIRMED on disk |
| Draft-B NPU variant | `models/qwen3-0.6b-pruned-6l/openvino-int4-npu/` | ABSENT — not testable |

Note: Only Draft-A (Qwen3-0.6B 28L INT4) has an NPU-compiled variant. Draft-B
(pruned 22L) has GPU variants only.

#### Evidence Collection

Task 4.2b (executed 2026-03-02, branch `feature/p5-task4-2-combined-rerun`):
- T-GPU-REF (T-01): Qwen3-14B/GPU + Draft-A/GPU, TPS=10.87, AR=0.4568 ✅
- T-NPU-01 (T-05): Qwen3-14B/GPU + Draft-A/NPU — **FAILED: VPUX LLVM ABORT**
  - Root cause: `as_convolution` decomposition pass → degenerate tensor `(1x0x1x1xf16)` for `self_attn.v_proj`
  - Error: `IE.Convolution` channels mismatch `0 != 8` → `LLVM ERROR: Failed to infer result type(s)` → `SIGABRT`
  - Failure stage: model compilation (before any inference)
  - Failure class: `LLVM_ABORT_VPUX_COMPILER` — deterministic, not retried
- Evidence artifact: `phase2_gates/evidence/p5_task4_2b_npu_draft_comparison.json` ✅ written

#### Disposition Criteria

| Outcome | Status Update | Carry-Forward |
|---------|--------------|---------------|
| T-NPU-01 TPS > T-GPU-REF TPS | ADOPTED — NPU as draft device for all profiles | All Task 4.3+ use NPU draft |
| T-NPU-01 TPS ≤ T-GPU-REF TPS | REJECTED — GPU draft confirmed superior | ADR-011 §2.1 extended to cover draft device |
| Pipeline construction failure | REJECTED (by default) | GPU draft carries forward |

**ACTUAL OUTCOME (2026-03-02):** Pipeline construction failure — `LLVM_ABORT_VPUX_COMPILER` →  
**STATUS: REJECTED.** GPU draft device (Draft-A, Qwen3-0.6B 28L INT4, `models/qwen3-0.6b/openvino-int4-gpu/`)  
carries forward to all Task 4.3+ profiles. §2.1 scope extends to draft device allocation.

#### Re-Evaluation Trigger — Heterogeneous Spec-Decode

The VPUX compiler bug that causes this LLVM ABORT has been root-caused and patched
(PRs [#265](https://github.com/openvinotoolkit/npu_compiler/pull/265) and
[#266](https://github.com/openvinotoolkit/npu_compiler/pull/266) submitted to
`openvinotoolkit/npu_compiler`). See `docs/VPUX_CONVERTFCTOCONV_BUG_FIX.md` for
full analysis.

**If both conditions are met, ADR-011 §2.4 and ADR-012 draft device allocation
should be re-evaluated:**

1. Upstream merges the fix (or an equivalent) into an OpenVINO release that ships
   with the corrected VPUX compiler, AND
2. OpenVINO GenAI exposes per-model device placement in the `draft_model()` API
   (or an equivalent mechanism for heterogeneous GPU-target / NPU-draft pipelines).

Heterogeneous speculative decoding is the architecturally optimal configuration for
Lunar Lake: the NPU draft model runs concurrently on NCE while the GPU processes
KV cache, with zero-copy LPDDR5X token handoff. If empirical benchmarks on the
fixed pipeline show NPU-draft TPS exceeding GPU-draft TPS (currently 10.87 tps at
4K), this ADR would be amended to restore NPU as the draft device — reversing only
§2.4 REJECTED status while keeping §2.1–§2.3 (full-model NPU retirement) intact.

#### What Does NOT Change Regardless of Outcome

- PA runs exclusively on GPU (ADR-010/ADR-011 §2.1 immutable)
- No speculative draft token is ever final PA output
- NPU remains retired from all full-model inference workloads
- Memory ceiling (ADR-005) and fail-closed architecture unchanged

---

## 3. Consequences

### 3.1 What Changes

1. **AO device allocation:** `NPU` → `GPU`. Config section `[npu]` → `[gpu]`.
   `priority = 1` removed (GPU has no priority mechanism; both PA and AO share
   the GPU, sequenced by the measured boot ordering — PA compiles first, AO second).

2. **NPU scheduling constants deprecated:** `NPU_ORCH_PRIORITY`,
   `NPU_PA_PRIORITY`, `NPU_SCHEDULING_MODEL`, `NPU_PARALLELISM_RATIO` —
   all retain values for backward compatibility but are marked DEPRECATED.
   New constant: `AO_DEVICE = "GPU"`.

3. **Model selection reopened:** `PA_MODEL_SIZE_PARAMS`, `ORCH_MODEL_SIZE_PARAMS`,
   `PA_OV_PATH` — marked PROVISIONAL pending P5-005a results. The Qwen2.5-1.5B
   model remains operational as a fallback but is expected to be replaced by a
   Qwen3 model.

4. **copilot-instructions.md:** `<device_allocation>` updated to reflect
   all-GPU inference. Phase 5 directive updated to note model selection is open.

5. **IMPLEMENTATION_PLAN.md:** Locked Models table updated — AO device column
   changed, model selection note added.

### 3.2 What Does NOT Change

1. **Semantic Router on CPU.** No change.
2. **Fail-Closed architecture.** GPU inference timeout → DENY. Same guarantee.
3. **Weight integrity verification.** SHA-256 on source `.bin` file. Device-agnostic.
4. **mTLS on vsock.** Unrelated to inference device.
5. **Agentic JWT lifecycle.** Unrelated to inference device.
6. **Measured Boot Sequence.** PA still boots first, establishes CA.
7. **Action Authorization Boundary (AAB).** JWT still required for every tool-call.
8. **31.323 GB memory ceiling.** Unchanged — GPU uses shared LPDDR5X.
9. **4,096 token hard caps.** Input/output caps remain (P5-001: DO-NOT-EXPAND).
10. **Deterministic execution.** Temperature=0 equivalent on GPU, same as before.

### 3.3 GPU Contention Model

With both PA and AO on the same GPU, a new contention model applies:

| Factor | Assessment |
|--------|-----------|
| PA + AO simultaneous inference | LOW RISK — PA is a ~78ms burst classification; AO is streaming generation. They are sequentially gated by the boot ordering and JWT lifecycle (PA must ALLOW before AO generates). |
| DWM compositing contention | LOW — Same as ADR-010 assessment. PA is a short burst. |
| Shared LPDDR5X memory pressure | MEDIUM — Both models' weights in VRAM simultaneously. Budget: PA weights (~1 GB) + AO weights (TBD, up to ~8 GB for 14B INT4) + KV caches. Must fit within 15,507 MB available (ADR-006). P5-005a will validate. |
| Model compilation time | LOW — GPU compilation is faster than NPU. Both models compile at boot. |

### 3.4 Residual Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| GPU VRAM exhaustion with larger model | MEDIUM | P5-005a explicitly measures peak RSS; 15,507 MB budget enforced; fail-closed on OOM |
| No hardware-level scheduling between PA and AO | LOW | Sequential gating by JWT lifecycle — AO cannot generate until PA has classified and issued JWT |
| Model selection delay | LOW | Qwen2.5-1.5B remains operational as fallback while P5-005a completes |
| NPU skill atrophy | INFORMATIONAL | NPU driver and validation scripts preserved; can be re-enabled for future use cases |

---

## 4. Evidence

- ADR-010 (PA to GPU): `docs/adrs/ADR-010-PA-Device-Allocation-GPU-Classification.md`
- ADR-008 (NPU scheduling): `docs/adrs/ADR-008-NPU-Concurrent-Scheduling-Characterization.md`
- P5-004 multi-device matrix: `phase2_gates/evidence/p5_multi_device_capability_matrix.json`
- P5-004 disposition: `docs/FEASIBILITY_MULTI_DEVICE_CAPABILITY.md`
- P5-005 blocked evidence: `phase2_gates/evidence/p5_unified_model_feasibility_matrix.json`
- P5-005a viability check: `phase2_gates/evidence/p5_005a_viability_check.json`
- NPU latency benchmark: `phase2_gates/evidence/npu_latency_benchmark.json`
- Task 4.2 corrected draft comparison: `phase2_gates/evidence/p5_task4_2_draft_model_comparison.json`
- Task 4.2b NPU draft device comparison: `phase2_gates/evidence/p5_task4_2b_npu_draft_comparison.json`

---

## 5. Rollback

If GPU-only inference proves infeasible (e.g., VRAM exhaustion with target model):

1. Revert AO config `[gpu]` → `[npu]`, `device = "GPU"` → `device = "NPU"`
2. Restore `NPU_ORCH_PRIORITY = 1` as active constant
3. Re-pin model to Qwen2.5-1.5B-Instruct (NPU-compatible)
4. ADR-010 device allocation table becomes authoritative again
5. Mark ADR-011 as SUPERSEDED with rollback rationale
