---
title: OPENVINO_CONTRIBUTION_PLAN_MARCH_2026
status: archived
area: portfolio
---

# OpenVINO Contribution Plan — March 2026

**Lead Architect**: BlarAI
**Hardware**: Intel Core Ultra 7 258V (Lunar Lake), Arc 140V (Xe2, 8 Xe-cores, 16 GB shared), 32 GB LPDDR5X-8533
**OS**: Windows 11 Pro Build 26200
**OpenVINO**: 2026.0.0-20965-c6d6a13a886-releases/2026/0
**Generated**: 2026-03-13

---

## Strategic Position

Three advantages most contributors don't have:
1. **Arc 140V (Xe2, Lunar Lake)** — current-gen consumer iGPU that few external contributors test on
2. **Existing PRs with Intel** — #34651 (openvino), #265/#266 (npu_compiler) establish credibility
3. **Deep Qwen3.5 domain knowledge** — architecture, hybrid cache, GatedDeltaNet internals

---

## Completed Work

### Opportunity 2: ScatterUpdate GPU Bug Triage (#34532) — DONE

**Comment posted**: https://github.com/openvinotoolkit/openvino/issues/34532
**Evidence**: `phase2_gates/evidence/issue34532_test_results.json`
**Draft**: `docs/ISSUE_34532_COMMENT.md`

Confirmed two bugs on Arc 140V (Xe2 iGPU):
- **Bug 1**: Standalone ScatterUpdate has FP16 precision loss (4.08e-4 max diff)
- **Bug 2**: ScatterUpdate inside Loop body crashes during GPU compilation

**New finding**: `INFERENCE_PRECISION_HINT=f32` does NOT fix the Loop crash — error changes from `data_type: f16` to `data_type: f32` but the layout is still missing. Two separate sub-bugs: FP16 down-cast AND missing ScatterUpdate kernel for Loop body context.

---

## Ecosystem Scan — Top 10 Opportunities

### Tier 1: Push Existing PRs Through Review (Highest ROI)

#### A. PR #34651 — NPU Dynamic Shape Guard
- **Issue**: [openvino#34617](https://github.com/openvinotoolkit/openvino/issues/34617)
- **PR**: [openvino#34651](https://github.com/openvinotoolkit/openvino/pull/34651)
- **Status**: Open, no reviews yet, assigned to Munesh-Intel + YuChern-Intel
- **What it does**: \~25-line early validation guard in `Plugin::compile_model()` to detect unbounded dynamic dimensions before they reach the VPUX compiler
- **Action needed**: Engage in PR comments, address CI feedback, ping reviewers
- **Impact**: Closes #34617 plus relates to 4 historical NPU dynamic-shape bugs (#32466, #24619, #26375, #26357)

#### B. PRs #265/#266 — NPU Compiler LLVM ABORT Fix
- **Issue**: [openvino#34450](https://github.com/openvinotoolkit/openvino/issues/34450)
- **PRs**: [npu_compiler#265](https://github.com/openvinotoolkit/npu_compiler/pull/265), [npu_compiler#266](https://github.com/openvinotoolkit/npu_compiler/pull/266)
- **What it does**: Fixes degenerate 0-channel tensor crash (`tensor<1x0x1x1xf16>`) from Qwen3-0.6B INT4 per-group quantization
- **Action needed**: Engage review cycle
- **Impact**: Unblocks NPU-based speculative decoding for INT4 Qwen3 models

---

### Tier 2: Quick Diagnostic/Testing Wins (Selected Focus)

#### C. Issue #33946 — Qwen3-VL 8B INT4 Performance on Arc 140V (ACTIVE — see plan below)
- **URL**: https://github.com/openvinotoolkit/openvino/issues/33946
- **Status**: UNASSIGNED, last activity Feb 2026, no Intel engineer response
- **What's needed**: Two users with Arc 140V report only 8 tok/s on Qwen VL 8B INT4. No diagnosis posted.
- **Effort**: Low (\~30 min benchmarking)
- **Impact**: Medium — establishes you as the go-to Arc 140V diagnostic resource

#### D. Issue #32791 — INT4 gpt-oss-20b Garbage Output on GPU
- **URL**: https://github.com/openvinotoolkit/openvino/issues/32791
- **Status**: UNASSIGNED, last activity Nov 2025
- **What's needed**: INT4 MoE model produces all-zeros on GPU. Fix targeted for OV 2025.4. LNL Xe2 is in the optimized tier. Test if fix landed in 2026.0.0.
- **Effort**: Low (testing)
- **Impact**: Low-medium — revives stale issue. RISK: model needs \~13GB RSS (tight on 32GB shared)
- **Recommendation**: SKIP for now due to memory pressure risk

#### E. Issue #33776 — GLM-4.7-Flash + Qwen3.5 Model Support Tracking
- **URL**: https://github.com/openvinotoolkit/openvino/issues/33776
- **Status**: UNASSIGNED, last activity Mar 2026
- **What's needed**: Feature request expanded to include Qwen3.5. @rkazants posted PR #1634.
- **Effort**: Low (already doing this work)
- **Impact**: Medium — visible in a tracked feature request

---

### Tier 3: Code Contributions (Higher Effort)

#### F. Issue #34532 — GPU ScatterUpdate Precision Fix
- **URL**: https://github.com/openvinotoolkit/openvino/issues/34532
- **Status**: Assigned to Munesh-Intel + Wan-Intel, no PR yet
- **What's needed**: Fix the GPU plugin precision-lowering pass that incorrectly downcasts ScatterUpdate to FP16 inside Loop bodies. Root cause in `src/plugins/intel_gpu/src/graph/graph_optimizer/add_required_reorders.cpp`.
- **Effort**: HIGH (C++ GPU plugin internals)
- **Impact**: VERY HIGH — unblocks Qwen3.5 GPU inference entirely
- **Risk**: May step on Intel engineers' toes since it's already assigned

#### G. Issue #3361 (openvino.genai) — Flux.1 INT4 Blurry Output on GPU
- **URL**: https://github.com/openvinotoolkit/openvino.genai/issues/3361
- **Status**: UNASSIGNED
- **What's needed**: Same class of FP16 precision problem as #34532. INT4 + FP16 accumulation causes numerical errors in image generation.
- **Effort**: Medium
- **Impact**: Medium — connects to the broader FP16 precision theme

#### H. Issue #3479 (openvino.genai) — C API Word Timestamps for Whisper
- **URL**: https://github.com/openvinotoolkit/openvino.genai/issues/3479
- **Status**: UNASSIGNED
- **What's needed**: Add C API bindings for `word_timestamps` in WhisperPipeline. C++ and Python implementations already exist.
- **Effort**: Medium (C API binding work)
- **Impact**: Low — clean scope but unrelated to Qwen3.5 focus

---

### Tier 4: Thought Leadership

#### I. Issue #3448 (openvino.genai) — Speculative Speculative Decoding
- **URL**: https://github.com/openvinotoolkit/openvino.genai/issues/3448
- **Status**: UNASSIGNED, feature request, early triage
- **What's needed**: Design proposal for "Speculative Speculative Decoding" (arXiv 2603.03251)
- **Effort**: Medium (design document, no code)
- **Impact**: High for positioning — you're already running speculative decoding (Qwen3-14B + Qwen3-0.6B)

---

### Opportunity 3: openvino.genai Feature Request — Qwen3.5 Hybrid Cache

**Feature request content drafted**: `docs/GENAI_FEATURE_REQUEST_QWEN35.md`
**Status**: Ready to submit

**Key discovery**: Intel's PR #3359 in openvino.genai already builds hybrid pipeline infrastructure for 2026.1 milestone, supporting LFM2 as the primary hybrid test case. Our feature request asks Intel to validate Qwen3.5 against this same infrastructure and add it to the CI test matrix.

**Submission steps**:
1. Go to https://github.com/openvinotoolkit/openvino.genai/issues/new
2. If template chooser appears, click "Open a blank issue"
3. Title: `[Feature Request] Qwen3.5 hybrid cache pipeline support (conv_state + recurrent_state + KV-cache)`
4. Body: Paste contents of `docs/GENAI_FEATURE_REQUEST_QWEN35.md`
5. Labels: `category: LLM` if available
6. Submit

---

## Active Plan: Diagnose Issue #33946

### Context

**Issue**: [openvinotoolkit/openvino#33946](https://github.com/openvinotoolkit/openvino/issues/33946)
**Status**: OPEN, UNASSIGNED, no Intel engineer has responded
**Reporters**: Two users with Arc 140V report only 8 tok/s on Qwen VL 8B INT4 — expected \~21-24 tok/s
**Model**: `Qwen/Qwen2.5-VL-7B-Instruct` (confirmed — "Qwen3-VL-8B" does not exist on HuggingFace)

### Why This Is a Good Fit

1. **Same GPU** — Arc 140V, identical to the reporters
2. **Newer OpenVINO** — 2026.0.0 vs their 2025.3.0 — if perf improved, that's useful data
3. **Qwen expertise** — VLM architecture knowledge from Qwen3.5 work
4. **Low effort** — \~30 min of benchmarking, no code changes needed
5. **Community visibility** — Unassigned issue with no Intel response

### What the Reporters Likely Got Wrong

Based on community diagnosis (krgkaushik's comments):
- May be benchmarking the **vision encoder** instead of the **language model**
- May not have used `stateful=True` during export
- May be including first-token latency (vision prefill) in the average
- May have the wrong device target

### Step-by-Step Execution

#### Step 1: Identify the exact model

Confirmed: `Qwen/Qwen2.5-VL-7B-Instruct` (4.78M downloads, the latest official \~8B VL model from Qwen).

#### Step 2: Export the model to OpenVINO IR (INT4)

Uses BlarAI `.venv` (full openvino + genai + optimum stack):

```powershell
.venv\Scripts\python.exe -m optimum.exporters.openvino \
  --model "Qwen/Qwen2.5-VL-7B-Instruct" \
  --weight-format int4 \
  --task image-text-to-text \
  models/qwen25-vl-7b-int4
```

**Memory**: INT4 8B model ≈ 4-5GB. Fits comfortably on Arc 140V.
**Time**: \~10-20 min for export + download.

#### Step 3: Run controlled `benchmark_app` tests

Isolates the inference engine from Python overhead:

```powershell
# Language model on GPU (the key metric)
benchmark_app -m models/qwen25-vl-7b-int4/openvino_language_model.xml -d GPU -hint tput -t 15

# Language model on CPU (baseline comparison)
benchmark_app -m models/qwen25-vl-7b-int4/openvino_language_model.xml -d CPU -hint tput -t 15

# Vision encoder on GPU (should be slower — not the right thing to benchmark)
benchmark_app -m models/qwen25-vl-7b-int4/openvino_vision_encoder.xml -d GPU -hint tput -t 15
```

**Expected results** (based on official qwen3-8b benchmarks for 7-258V):
- Language model GPU: \~21-24 tok/s
- Language model CPU: \~10-15 tok/s
- Vision encoder GPU: Slower (this is normal, not the bottleneck)

#### Step 4: Run end-to-end VLM inference with timing

```python
from openvino_genai import VLMPipeline
from PIL import Image
import time

pipe = VLMPipeline("models/qwen25-vl-7b-int4", device="GPU")
image = Image.new("RGB", (224, 224), color="red")  # minimal image

start = time.time()
result = pipe.generate("Describe this image in detail.", images=[image], max_new_tokens=128)
elapsed = time.time() - start
print(f"Result: {result}")
print(f"Time: {elapsed:.2f}s")
```

#### Step 5: Save results and draft comment

**Files created**:
- `scripts/test_issue33946_qwenvl_perf.py` — unified benchmark script (DONE)
- `scripts/run_issue33946_benchmark.ps1` — PowerShell wrapper (DONE)
- `phase2_gates/evidence/issue33946_benchmark_results.json` — structured results (pending run)
- `docs/ISSUE_33946_COMMENT.md` — paste-ready GitHub comment (pending results)

#### Step 6: Post on GitHub

Comment on [#33946](https://github.com/openvinotoolkit/openvino/issues/33946) with:
- Environment table (OV 2026.0.0, Arc 140V, Windows 11)
- `benchmark_app` results for language model vs vision encoder (GPU vs CPU)
- End-to-end VLMPipeline inference timing
- Diagnosis of what the original reporters likely measured wrong
- Concrete recommendations

### How to Run

```powershell
cd C:\Users\mrbla\BlarAI
.\scripts\run_issue33946_benchmark.ps1
```

**First run**: \~20+ min (downloads \~16GB model, then exports to INT4 IR)
**Subsequent runs**: \~2 min (skips export, runs benchmarks only)

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Model download is large (\~16GB for full VL model) | INT4 export reduces to \~4-5GB on disk |
| Export may fail (VLM export is complex) | Use standard `optimum-cli` path, not PR #1634 branch |
| GPU driver issues on Windows | Check Intel driver version in diagnostic output |
| 8 tok/s reproduces even on 2026.0.0 | That's valuable data — confirms a real bug, not a user error |
| gpt-oss-20b memory pressure (\~13GB RSS) | SKIP this issue — too close to memory limit |
| Bash shell broken (MSYS2 0xC0000142) | Use PowerShell scripts with direct venv Python paths |

---

## Verification

1. Confirm `.\scripts\run_issue33946_benchmark.ps1` runs to completion
2. Check JSON results: `phase2_gates\evidence\issue33946_benchmark_results.json`
3. Review draft comment: `docs\ISSUE_33946_COMMENT.md`
4. Post comment on #33946
5. Post feature request on openvino.genai (from `docs\GENAI_FEATURE_REQUEST_QWEN35.md`)

---

## Zero Regression Risk Compliance

- **No BlarAI production code modified** — only new standalone scripts and evidence files
- **Existing venvs reused** — `.venv` for benchmarks, `optimum-intel-test-env` for ScatterUpdate repro
- **No model downloads into production paths** — exported models go to `models/` directory
- **All comments posted manually** — Lead Architect reviews before posting

---

## Files Reference

| File | Purpose | Status |
|------|---------|--------|
| `scripts/test_issue34532_scatterupdate.py` | ScatterUpdate GPU repro script | DONE |
| `scripts/run_issue34532_repro.ps1` | PowerShell wrapper for #34532 | DONE |
| `scripts/test_issue33946_qwenvl_perf.py` | VLM perf benchmark script | DONE |
| `scripts/run_issue33946_benchmark.ps1` | PowerShell wrapper for #33946 | DONE |
| `phase2_gates/evidence/issue34532_test_results.json` | ScatterUpdate results | DONE |
| `phase2_gates/evidence/issue33946_benchmark_results.json` | VLM benchmark results | PENDING |
| `docs/ISSUE_34532_COMMENT.md` | Posted GitHub comment for #34532 | POSTED |
| `docs/ISSUE_34532_BUG_TRIAGE.md` | Full bug triage record | DONE |
| `docs/GENAI_FEATURE_REQUEST_QWEN35.md` | Feature request for openvino.genai | READY |
| `docs/ISSUE_33946_COMMENT.md` | GitHub comment for #33946 | PENDING |

---

## Session Assessment — 2026-03-13

### What was accomplished

The **#34532 ScatterUpdate comment** was the one genuinely valuable contribution
from this session. It provided Intel with:
- Xe2 architecture confirmation (new data — original report was Xe HPG only)
- New finding: `INFERENCE_PRECISION_HINT=f32` does NOT fix the Loop crash,
  revealing two distinct sub-bugs (FP16 down-cast AND missing Loop kernel)
- Professional-grade reproduction on consumer Lunar Lake hardware

### What was deprioritized and why

| Item | Why deprioritized |
|------|-------------------|
| openvino.genai feature request | PR #3359 already builds hybrid cache infra. @rkazants knows the tensor shapes. Marginal value. |
| #33946 VLM perf diagnostic | Different hardware (Arrow Lake-H vs Lunar Lake), different OV version, different OS. Our results wouldn't diagnose their problem. Community member already posted diagnostic questions twice — reporter never responded. |
| #33776 Qwen3.5 tracking comment | Just "I'm also interested" — noise, not signal. |
| Push existing PRs | Pinging reviewers isn't a contribution. They'll review when ready. |
| Fix sdpa_mask_without_vmap | @rkazants maintains the transformers-v5 branch and knows the export is broken. Fix is likely in progress. We'd duplicate work or create merge conflicts. |
| Fix ScatterUpdate GPU kernel | Assigned to Munesh-Intel + Wan-Intel. Deep C++ GPU plugin code requiring domain expertise we don't have. Risk of submitting suboptimal fix or annoying assigned engineers. |

### Current blocking situation

Both blockers for Qwen3.5 on Arc 140V are being worked on by the right people:

| Blocker | Who's on it | Our role |
|---------|-------------|----------|
| Export broken (sdpa_mask signature mismatch) | @rkazants (optimum-intel transformers-v5) | Wait for fix |
| GPU crash (ScatterUpdate in Loop bodies) | Munesh-Intel + Wan-Intel (openvino #34532) | Already contributed new data |

### When to re-engage

Re-engage when EITHER of these ships:
1. **PR #1634 export works** → immediately test Qwen3.5-0.8B on Arc 140V (CPU first, then GPU when #34532 is fixed). This is when real model testing on consumer Lunar Lake becomes genuinely high-value.
2. **#34532 ScatterUpdate fix ships** → re-run the repro script to confirm, then test full Qwen3.5 GPU inference.

Monitor these URLs:
- https://github.com/huggingface/optimum-intel/pull/1634
- https://github.com/openvinotoolkit/openvino/issues/34532
- https://github.com/openvinotoolkit/openvino.genai/pull/3359

### Prioritized Action Queue (revised)

| Priority | Action | Effort | Status |
|----------|--------|--------|--------|
| 1 | ~~Reproduce #34532 ScatterUpdate bug on Arc 140V~~ | Low | DONE |
| 2 | Wait for upstream blockers to resolve | — | WAITING |
| 3 | Test Qwen3.5-0.8B export + inference when PR #1634 works | Medium | BLOCKED |
| 4 | Test Qwen3.5 GPU inference when #34532 is fixed | Medium | BLOCKED |
| 5 | Submit openvino.genai feature request (optional) | Low | DEFERRED |
