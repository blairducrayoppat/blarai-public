---
title: FEASIBILITY_MULTI_DEVICE_CAPABILITY
status: archived
area: portfolio
---

# P5-FEASIBILITY-004 — Multi-Device Capability Matrix (NPU/GPU/CPU)

**Date:** 2026-02-26 (UTC)  
**Branch:** `feature/p5-feasibility-004-multi-device`  
**Scope:** Empirical multi-device generation benchmarking with explicit NPU `MAX_PROMPT_LEN` scaling

---

## 1) NPU `MAX_PROMPT_LEN` Scaling Results

Primary evidence:
- `phase2_gates/evidence/p5_multi_device_capability_matrix.json`

Environment:
- OpenVINO `2026.0.0`
- OpenVINO GenAI `2026.0.0.0`
- AC power locked (`power_plugged=true`)

NPU compile and runtime summary (Qwen2.5-1.5B, NPU only):

| MAX_PROMPT_LEN | Pipeline compile | Highest successful user prompt | Outcome |
|---:|---:|---:|---|
| 1024 | 39.1s | 896 | pass (bounded by configured prompt envelope) |
| 2048 | 90.8s | 1800 | pass |
| 3072 | 115.7s | 3000 | pass |
| 4096 | 136.1s | 4000 | pass |
| 6144 | 166.1s | 6000 | pass |
| 8192 | 209.7s | 8000 | pass |

Key finding:
- The prior `1024` wall is **overturned** when NPU pipeline config sets higher `MAX_PROMPT_LEN`.
- This confirms prior failures were driven by software-default configuration, not a hard hardware ceiling at 1024.

Representative NPU runtime measurements:
- `MAX_PROMPT_LEN=8192`, user `8000`: `p95 latency_total_ms=8858.24`, `mean decode_tokens_per_sec=3.28`, `valid=5/5`
- `MAX_PROMPT_LEN=8192`, user `4096`: `p95 latency_total_ms=5391.11`, `mean decode_tokens_per_sec=2.97`, `valid=5/5`

---

## 2) GPU Generation Results

Models tested:
- Qwen2.5-1.5B (`models/qwen2.5-1.5b-instruct/openvino-int4-npu`, compiled for GPU)
- Qwen3-1.7B (`models/qwen3-1.7b/openvino-int4`, compiled for GPU)

Results:
- Both models loaded and generated successfully through 4096 user-token band.
- At 4096 user tokens:
  - GPU + Qwen2.5: `p95 latency_total_ms=1296.75`, `mean tps=53.41`
  - GPU + Qwen3: `p95 latency_total_ms=3612.28`, `mean tps=36.27`

Interpretation:
- GPU generation is materially faster than NPU generation at overlapping prompt lengths.
- On this platform, Qwen2.5 is faster than Qwen3 for generation on GPU.

---

## 3) CPU Generation Results

Models tested:
- Qwen2.5-1.5B (CPU)
- Qwen3-1.7B (CPU)

Results:
- Both models loaded and generated successfully through 4096 user-token band.
- At 4096 user tokens:
  - CPU + Qwen2.5: `p95 latency_total_ms=6119.10`, `mean tps=21.11`
  - CPU + Qwen3: `p95 latency_total_ms=6353.78`, `mean tps=15.42`

Interpretation:
- CPU is viable as fallback generation path but is slower than GPU.
- CPU remains faster than NPU for many overlapping prompt bands in this run.

---

## 4) Cross-Device Comparison (Representative Bands)

Qwen2.5 where all three devices are available:

| User prompt tokens | NPU (configured) | GPU (Qwen2.5) | CPU (Qwen2.5) |
|---:|---|---|---|
| 512 | p95=9060.04ms, tps=14.15 (`MAX_PROMPT_LEN=4096`) | p95≈sub-1.3s class, higher throughput | p95≈multi-second, below GPU |
| 2048 | p95=10183.70ms, tps=12.59 (`MAX_PROMPT_LEN=4096`) | substantially lower latency than NPU | lower latency than NPU, higher than GPU |
| 4096 | p95=5391.11ms, tps=2.97 (`MAX_PROMPT_LEN=8192`) | p95=1296.75ms, tps=53.41 | p95=6119.10ms, tps=21.11 |

Additional long-context NPU point:
- 8000 user tokens (`MAX_PROMPT_LEN=8192`) succeeded on NPU with `valid=5/5`.

---

## 5) Model Comparison (Qwen2.5 vs Qwen3 on GPU/CPU)

Aggregate trend across tested prompt bands:
- GPU average p95 latency:
  - Qwen2.5: `1032.54ms`
  - Qwen3: `2978.85ms`
- CPU average p95 latency:
  - Qwen2.5: `3427.62ms`
  - Qwen3: `6041.85ms`
- Throughput trend (mean tokens/s) also favors Qwen2.5 on both GPU and CPU in this run.

Output quality note:
- This milestone prioritized capability/performance and deterministic stability metrics.
- No formal human-graded quality rubric was applied; no qualitative model-switch recommendation is made from subjective output alone.

---

## 6) Device Allocation Recommendation

Answers to milestone questions:

A. True NPU maximum context when configured:
- Demonstrated successful generation through **8000 user tokens** with `MAX_PROMPT_LEN=8192`.
- Therefore, practical measured ceiling in this run is **at least 8000 user tokens**.

B. GPU vs NPU for generation speed/context:
- NPU can support much larger prompt windows when configured.
- GPU is consistently faster at overlapping lengths in this run.

C. CPU viability:
- CPU is viable as fallback generation path and supports tested long prompts, but slower than GPU.

D. Architecture outcome:
- **Recommended outcome: `HYBRID_NPU_GPU`**
  - Keep NPU context expansion capability available (for very long-context workloads).
  - Prefer GPU as primary generation path where low latency/throughput are dominant.
  - Keep CPU as deterministic fallback when GPU/NPU path is unavailable.

---

## 7) Disposition

- **Disposition:** `HYBRID_NPU_GPU`
- **Gate status:** `READY_FOR_ARCH_RECOMMENDATION`
- **Prior 1024-wall conclusion:** **OVERTURNED** (`npu_1024_wall_overturned=true`)
- **Quality gate (DCG):** All required checks `DCG-01..DCG-07` passed.
- **Memory safety:** No crash/OOM observed; max measured RSS peak `3919.58 MB` (well below 28GB warning threshold).

ADR impact:
- Any production architecture or runtime routing change remains ADR-gated before implementation.
