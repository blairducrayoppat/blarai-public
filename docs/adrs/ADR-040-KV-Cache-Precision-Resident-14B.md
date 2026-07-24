# ADR-040 — KV-Cache Precision for the Resident 14B (Assistant Orchestrator)

**Status:** Accepted (records the current posture + the measured evidence; the 14B → INT8 flip remains gated on the #715 answer-quality A/B)
**Date:** 2026-07-15
**Deciders:** LA (quality/enablement posture); technical analysis this session
**Related:** ADR-011 (all LLM inference on GPU), ADR-012 (Qwen3-14B + speculative decoding), DEC-03 (max context 16384), DEC-07 (inference precision pinned to f16 — a *compute*-precision decision, distinct from KV-cache precision), #709 (KV-precision sweep), #715 (INT8-in-production answer-quality A/B — the open gate)

## Context

On the 31.323 GiB unified-memory box, the **KV cache is the largest *elastic* memory cost**: Qwen3-14B needs ~160 KiB/token at FP16 (2 × 40 layers × 8 KV-heads × 128 head-dim × 2 bytes), so a 32K context is **5.0 GiB of KV** — competing directly with the ~9.7 GB resident weights and the OS for the last few GB of headroom, and it is the single biggest *reclaimable* slice of the fixed budget.

OpenVINO GenAI exposes GPU KV-cache precision via the `KV_CACHE_PRECISION` property (`u8` / `u4`; FP16 = property unset). The BlarAI surface is `[gpu].kv_cache_precision` in the Assistant Orchestrator `default.toml`, shipped **empty (= FP16)**.

## Measured evidence (2026-07-01 sweep, #709)

Harness `scripts/benchmark_kv_cache_sweep.py`; data `docs/performance/kv_cache_sweep_ov2026_2_1_0_2026-07-01_19-10-33.json`; narrative in `PERFORMANCE_LOG.md` (2026-07-01). Qwen3-14B INT4, GPU, plain autoregressive, warmed to a TTFT plateau, N=3 per combo.

| KV precision | KV @ 32K | TTFT 16K (median) | TTFT 32K (median) |
|---|---|---|---|
| **FP16** (unset) | 5.00 GiB | 45.8 s | 368.9 s |
| **INT8** (`u8`) | 2.50 GiB | ~46.8 s | **159.0 s** |
| **INT4** (`u4`) | 1.25 GiB | 51.5 s | 174.5 s |

- **Two regimes.** At 16K, prefill is **compute-bound** → KV quantization is slightly *slower* (dequant overhead, no bandwidth relief). At 32K, prefill is **memory-bandwidth-bound** reading the large KV every step → quantization is a big *speed* win: **INT8 is 2.3× faster than FP16**.
- **INT8 (`u8`) is the sweet spot.** INT4 quarters the KV footprint but its 4-bit dequant makes it slightly slower than INT8 at 32K and carries the higher recall risk.
- The KV pool is resolvable as `cl_mem` in `GPU_MEMORY_STATISTICS` (an earlier 2026-06-29 attempt to measure it via host "Available" sampling returned an honest null — the pool is not host-visible on this unified-memory iGPU; GPU-allocation-level instrumentation was required).
- **INT8 KV is already live for the 30B coder** (OVMS `--kv_cache_precision u8`; co-residency + best-of-N runs), so INT8 KV is proven in the coder path.
- **Not measured:** answer **quality** under INT8/INT4 KV (the open gate — #715); KV precision above 32K; freq/temp/power traces.

## Decision

1. The product 14B (AO) ships **KV-cache precision = FP16 (unset)** — the conservative default — **until** the answer-quality A/B (#715) measures INT8's recall/quality impact at production context lengths.
2. **INT8 (`u8`) is the designated adopt-candidate on quality parity** (measured performance sweet spot; already proven on the 30B). **INT4 is not a candidate for the 14B** (marginal extra memory, worse speed, higher recall risk).
3. Enabling INT8 on the 14B is a **quality-posture change** and remains an **LA decision, gated on #715 passing**. The `[gpu].kv_cache_precision` knob is the single flip; no code change.
4. This ADR **supersedes the provisional 2026-07-01 DECISION_REGISTER note**, which recorded the two-regime lever but was explicitly left un-numbered pending #715.

## Consequences

- **No runtime change today** — the 14B stays FP16. The measured lever is now formally documented rather than living only in a performance-log entry.
- When #715 runs and passes, **~2.5 GiB of KV headroom + a 2.3× long-context prefill speedup** become available on the 14B via one config flip — material on a box where the last few GB decide whether a rich memory/retrieval index and the 14B can co-reside (see the memory-architecture direction in the 2026-07 design review, `docs/design/july.15.2026/`).
- If #715 shows INT8 degrades long-context recall beyond tolerance, the 14B stays FP16 and this ADR records that as the outcome.
- **Workload-tiered precision** (INT8 for long-context turns, FP16 for short interactive turns) is a possible refinement, out of scope until #715 sets the quality baseline.

## Evidence

`PERFORMANCE_LOG.md` (2026-07-01 entry) · `docs/performance/kv_cache_sweep_ov2026_2_1_0_2026-07-01_19-10-33.json` · `docs/DECISION_REGISTER.md` (2026-07-01 provisional note, now pointing here) · `services/assistant_orchestrator/config/default.toml` `[gpu].kv_cache_precision`.
