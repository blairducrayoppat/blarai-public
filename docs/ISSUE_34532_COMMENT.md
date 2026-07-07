### Confirmed on Intel Arc 140V (Xe2 iGPU, Lunar Lake)

Reproduced both bugs on consumer Xe2 integrated GPU using @Blackwood416's reproduction script.

**Environment:**

| | |
|---|---|
| CPU | Intel Core Ultra 7 258V (Lunar Lake) |
| GPU | Intel Arc 140V (Xe2, 8 Xe-cores, 16 GB shared) — iGPU |
| OpenVINO | 2026.0.0-20965-c6d6a13a886-releases/2026/0 |
| OS | Windows 11 Pro Build 26200 |
| Python | 3.11.9 |

**Results:**

| Test | CPU | GPU | GPU + `INFERENCE_PRECISION_HINT=f32` |
|------|-----|-----|--------------------------------------|
| Standalone ScatterUpdate | PASS (0.0) | FAIL (4.08e-4) | PASS (0.0) |
| Loop ScatterUpdate | PASS (0.0) | CRASH (`data_type: f16`) | CRASH (`data_type: f32`) |

**New finding — `INFERENCE_PRECISION_HINT=f32` does not fix the Loop crash:**

The `f32` hint successfully prevents the FP16 down-cast (the Loop crash message changes from `data_type: f16` to `data_type: f32`), but the compilation still fails because `add_required_reorders.cpp:342` cannot find *any* layout for ScatterUpdate inside a Loop body — regardless of data type. This suggests two separate issues in the Loop path:

1. **Unwanted FP16 down-cast** inside Loop bodies (addressed by `f32` hint)
2. **Missing ScatterUpdate layout/implementation for Loop body context** — no workaround available

**Xe2 confirmation:** The bug reproduces identically on Xe2 iGPU (Arc 140V, Lunar Lake) as reported on Xe HPG dGPU (Arc A580), confirming the issue is in the core GPU plugin ScatterUpdate kernel, not in an architecture-specific code path.

**Real-world impact:** This blocks GPU inference for Qwen3.5 models on OpenVINO. The GatedDeltaNet linear attention layers (24 out of 32 in Qwen3.5-9B) use a recurrent state update implemented as Loop + ScatterUpdate in [optimum-intel PR #1634](https://github.com/huggingface/optimum-intel/pull/1634). Without a Loop-compatible ScatterUpdate kernel, Qwen3.5 is CPU-only.

<details><summary>Full console output</summary>

```
======================================================================
OpenVINO Issue #34532 Reproduction: ScatterUpdate GPU Bug
======================================================================

OpenVINO:  2026.0.0-20965-c6d6a13a886-releases/2026/0
GPU:       Intel(R) Arc(TM) 140V GPU (16GB) (iGPU)
GPU Drv:   unavailable
CPU:       Intel(R) Core(TM) Ultra 7 258V
OS:        Windows 10.0.26200
Python:    3.11.9
Devices:   ['CPU', 'GPU', 'NPU']

======================================================================
Test 1: Standalone ScatterUpdate (no Loop)
======================================================================
  [CPU     ] PASS  max_diff=0.0000000000
  [GPU     ] FAIL  max_diff=0.0004076958
  [GPU_f32 ] PASS  max_diff=0.0000000000

======================================================================
Test 2: ScatterUpdate inside Loop body
======================================================================
  [CPU     ] PASS  max_diff=0.0000000000
  [GPU     ] CRASH Exception from src\inference\src\cpp\core.cpp:113: ...
  [GPU_f32 ] CRASH Exception from src\inference\src\cpp\core.cpp:113: ...

======================================================================
CRASH DETAILS
======================================================================

--- T2_GPU ---
RuntimeError: ...
Check 'correct_layout_selected' failed at
  src\plugins\intel_gpu\src\graph\graph_optimizer\add_required_reorders.cpp:342:
[GPU] No layout format available for
  scatterupdate:Loop_15533/1/ScatterUpdate_15526,
  impl_type: any (format: bfyx, data_type: f16)

--- T2_GPU_f32 ---
RuntimeError: ...
Check 'correct_layout_selected' failed at
  src\plugins\intel_gpu\src\graph\graph_optimizer\add_required_reorders.cpp:342:
[GPU] No layout format available for
  scatterupdate:Loop_15533/1/ScatterUpdate_15526,
  impl_type: any (format: bfyx, data_type: f32)
```

</details>
