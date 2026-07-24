---
title: ISSUE_34532_BUG_TRIAGE
status: archived
area: portfolio
---

# Bug Triage: OpenVINO #34532 — ScatterUpdate GPU Precision Loss & Loop Crash

**Status**: COMPLETE — Comment posted on 2026-03-13
**Posted Comment**: https://github.com/openvinotoolkit/openvino/issues/34532
**Draft**: `docs/ISSUE_34532_COMMENT.md`
**Issue**: https://github.com/openvinotoolkit/openvino/issues/34532
**Contribution Guide Reference**: Opportunity #2 in `docs/QWEN35_CONTRIBUTION_GUIDE.md`

---

## 1. Bug Summary

OpenVINO's GPU plugin has two distinct bugs in its `ScatterUpdate` kernel, reported by `@Blackwood416` on 2026-03-06 against an **Intel Arc A580 (Xe HPG, dGPU)**.

### Bug 1: Standalone ScatterUpdate — Silent FP16 Precision Loss

- **What**: When a simple `ScatterUpdate` model with all FP32 tensors is compiled for GPU, the GPU plugin silently down-casts intermediate computations to FP16, introducing \~5e-4 max absolute error.
- **Impact on Qwen3.5**: The recurrent state update `state = g * state + beta * (k^T @ v)` runs across 24 linear attention layers per token. Precision errors compound and produce garbled output.
- **Workaround**: `{"INFERENCE_PRECISION_HINT": "f32"}` fixes standalone case.

### Bug 2: ScatterUpdate Inside Loop Body — GPU Compilation Crash

- **What**: When `ScatterUpdate` is inside an OpenVINO `Loop` op body, GPU compilation crashes with:
  ```
  RuntimeError: ProgramBuilder build failed!
  Check 'correct_layout_selected' failed at
  src\plugins\intel_gpu\src\graph\graph_optimizer\add_required_reorders.cpp:342:
  [GPU] No layout format available for scatterupdate:Loop_.../ScatterUpdate_...,
  impl_type: any (format: bfyx, data_type: f16)
  ```
- **Root cause**: The GPU plugin down-casts to `f16` inside the Loop body despite FP32 declarations, then the graph optimizer can't find a valid layout for the FP16 ScatterUpdate.
- **Impact on Qwen3.5**: PR #1634 implements GatedDeltaNet's recurrent attention as a Loop containing ScatterUpdate. This crash is a **hard blocker** — no workaround known.
- **Workaround status**: Unknown whether `INFERENCE_PRECISION_HINT=f32` prevents the down-cast inside Loop bodies. Our script tests this.

---

## 2. Issue Timeline & Intel Response

| Date | Actor | Action |
|------|-------|--------|
| 2026-03-06 | @Blackwood416 | Filed issue with full repro script. Hardware: Arc A580 (Xe HPG), OpenVINO 2026.0.0 |
| 2026-03-06 | (auto) | Labels applied: `bug`, `support_request` |
| 2026-03-10 | @YuChern-Intel | Assigned to @Munesh-Intel and @Wan-Intel |
| 2026-03-10 | @Wan-Intel | Confirmed reproduction on "several machines". Escalated to relevant team. |
| 2026-03-12 | — | Issue remains OPEN. No linked PRs. No additional comments. |

**Key observation**: Intel engineers did NOT request additional reproduction data. However, no one has reported from Xe2 (Lunar Lake) hardware yet.

---

## 3. Why Our Reproduction Adds Value

| Data Point | Original Report | Our Contribution |
|-----------|----------------|------------------|
| GPU architecture | Xe HPG (Arc A580, discrete) | **Xe2 (Arc 140V, integrated, Lunar Lake)** |
| GPU type | dGPU | **iGPU** |
| Platform | Windows (unspecified) | **Windows 11 Pro Build 26200 (Lunar Lake)** |
| CPU | Not specified | **Intel Core Ultra 7 258V** |
| Loop + f32 workaround tested | No | **Yes** |
| Link to optimum-intel PR | Mentioned conceptually | **Direct cross-reference to PR #1634** |

**Value**: Confirms the bug spans GPU architecture generations (Xe HPG → Xe2), meaning the fix must be in the core ScatterUpdate kernel, not architecture-specific paths. Also tests the Loop+f32 workaround (new data).

---

## 4. Our Hardware & Environment

- **CPU**: Intel Core Ultra 7 258V (Lunar Lake)
- **GPU**: Intel Arc 140V (Xe2, 8 Xe-cores, 16 GB shared memory, iGPU)
- **RAM**: 32 GB LPDDR5X-8533
- **OS**: Windows 11 Pro Build 26200
- **Python**: 3.11.9
- **OpenVINO**: 2026.0.0 (installed in `C:\Users\mrbla\optimum-intel-test-env`)
- **Venv location**: `C:\Users\mrbla\optimum-intel-test-env`

---

## 5. Scripts Created (Ready to Run)

### 5a. Python Reproduction Script

**Path**: `c:\Users\mrbla\BlarAI\scripts\test_issue34532_scatterupdate.py`
**Dependencies**: `openvino`, `numpy` (both already in the venv)
**Runtime**: \~10 seconds (synthetic tensors, no model download)

**What it does**:
1. Collects environment metadata (OpenVINO version, GPU name, driver, OS, Python)
2. **Test 1 — Standalone ScatterUpdate**: Builds a minimal `ScatterUpdate` model with FP32 tensors. Runs on CPU, GPU, and GPU+f32. Compares output against numpy reference. Reports max absolute diff.
3. **Test 2 — ScatterUpdate inside Loop**: Builds a Loop that iterates over timesteps using ScatterUpdate to accumulate scaled values. CPU produces `data * 2.0` as reference. GPU expected to crash.
4. Saves structured JSON results to `phase2_gates/evidence/issue34532_test_results.json`
5. Prints crash tracebacks at the end for easy copy-paste

### 5b. PowerShell Wrapper

**Path**: `c:\Users\mrbla\BlarAI\scripts\run_issue34532_repro.ps1`

**What it does**:
1. Activates `C:\Users\mrbla\optimum-intel-test-env`
2. Verifies OpenVINO is importable
3. Runs `test_issue34532_scatterupdate.py`

### 5c. How to Run

```powershell
cd C:\Users\mrbla\BlarAI
.\scripts\run_issue34532_repro.ps1
```

---

## 6. Actual Results (2026-03-13)

| Test | Device | Result |
|------|--------|--------|
| Test 1: Standalone ScatterUpdate | CPU | **PASS** (diff = 0.0) |
| Test 1: Standalone ScatterUpdate | GPU | **FAIL** (diff = 4.08e-4) — FP16 precision loss confirmed |
| Test 1: Standalone ScatterUpdate | GPU+f32 | **PASS** (diff = 0.0) — workaround works |
| Test 2: Loop ScatterUpdate | CPU | **PASS** (diff = 0.0) |
| Test 2: Loop ScatterUpdate | GPU | **CRASH** — `data_type: f16` |
| Test 2: Loop ScatterUpdate | GPU+f32 | **CRASH** — `data_type: f32` — **NEW FINDING: no workaround** |

### Key New Finding

The `INFERENCE_PRECISION_HINT=f32` workaround prevents the FP16 down-cast (error
message changes from `data_type: f16` to `data_type: f32`) but the Loop compilation
**still crashes** because the ScatterUpdate layout is missing for Loop body context
at ANY data type. This reveals two separate sub-bugs:

1. Unwanted FP16 down-cast inside Loop bodies (fixed by f32 hint)
2. Missing ScatterUpdate kernel for Loop body context regardless of dtype (NO workaround)

---

## 7. GitHub Comment Template (to fill after test results)

**Post to**: https://github.com/openvinotoolkit/openvino/issues/34532

```markdown
### Confirmed on Intel Arc 140V (Xe2, Lunar Lake)

Reproduced both bugs using @Blackwood416's script on consumer Xe2 integrated GPU hardware.

**Hardware:** Intel Core Ultra 7 258V (Lunar Lake), Arc 140V (Xe2, 8 Xe-cores, 16 GB shared)
**Software:** OpenVINO {version}, Windows 11 Pro Build 26200, Python 3.11.9

| Test | CPU | GPU | GPU + f32 hint |
|------|-----|-----|----------------|
| Standalone ScatterUpdate | {result} | {result} | {result} |
| Loop ScatterUpdate | {result} | {result} | {result} |

**Key finding:** Bug reproduces on Xe2 iGPU (Arc 140V), confirming this is not
specific to Xe HPG / Arc A580 discrete GPUs. The issue is in the core GPU plugin
ScatterUpdate kernel, not an architecture-specific code path.

{If Loop+f32 crashes}: The `INFERENCE_PRECISION_HINT=f32` workaround does NOT
prevent the Loop body crash — the GPU plugin still down-casts inside Loop bodies
regardless of the hint.

{If Loop+f32 works}: The `INFERENCE_PRECISION_HINT=f32` workaround DOES work for
Loop bodies, providing a temporary path for models like Qwen3.5.

<details><summary>Full console output</summary>

```
{paste full output here}
```

</details>

**Context:** I'm working on deploying Qwen3.5-0.8B on consumer Lunar Lake hardware.
The ScatterUpdate Loop crash blocks GPU inference for all 24 GatedDeltaNet linear
attention layers via the recurrent state update path in optimum-intel
[PR #1634](https://github.com/huggingface/optimum-intel/pull/1634). An FP32
workaround would be acceptable for initial enablement if the Loop crash can be
resolved with the precision hint.
```

---

## 8. Connection to Qwen3.5 / PR #1634

This bug is the **critical path blocker** for Qwen3.5 GPU inference on OpenVINO:

```
Qwen3.5 model
  → 24 GatedDeltaNet linear attention layers
    → Each layer does recurrent state update: state = g * state + beta * (k^T @ v)
      → PR #1634 implements this as Loop + ScatterUpdate in OpenVINO IR
        → GPU compilation CRASHES per #34532 Bug 2
```

Until #34532 is fixed, Qwen3.5 is **CPU-only** on OpenVINO. The FP32 workaround
(if it works for Loop bodies) would provide a temporary path at the cost of
performance (\~2x slower on GPU).

---

## 9. Remaining Steps After Command Execution is Fixed

1. Run `.\scripts\run_issue34532_repro.ps1` in PowerShell
2. Paste console output back to Claude
3. Claude fills in the comment template with actual results
4. Lead Architect reviews and posts on GitHub issue #34532

---

## 10. Known Issue: Bash Shell Broken

Claude Code's bash shell has a persistent MSYS2 fork failure (`0xC0000142` DLL collision).
All command execution must go through user-executed PowerShell scripts. The `rebaseall`
fix was attempted but did not resolve it. Next step: investigate alternative shell
configuration or MSYS2 reinstall.
