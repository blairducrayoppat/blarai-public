# PR #1634 Test Report: Qwen3.5-0.8B on Intel Arc 140V (Lunar Lake)

> **PR:** [huggingface/optimum-intel#1634](https://github.com/huggingface/optimum-intel/pull/1634) — "[OpenVINO] Support Qwen3.5" by @rkazants
> **Tested by:** @blairducrayoppat
> **Date:** 2026-03-12

---

### Test Report: Qwen3.5-0.8B on Intel Arc 140V (Lunar Lake)

Tested the `support_qwen3_5` branch with a real Qwen3.5-0.8B model on consumer Intel hardware.

**Hardware:**
| Component | Detail |
|-----------|--------|
| SoC | Intel Core Ultra 7 258V (Lunar Lake) |
| GPU | Intel Arc 140V (Xe2, 8 Xe-cores, 16 GB shared) |
| Memory | 32 GB LPDDR5X-8533 (shared) |
| NPU | Intel AI Boost (not used in this test) |

**Software:**
| Package | Version |
|---------|---------|
| OS | Windows 11 Pro Build 26200 |
| Python | 3.11.9 |
| OpenVINO | 2026.0.0-20965-c6d6a13a886 (releases/2026/0) |
| Transformers | 5.3.0.dev0 (main @ HEAD) |
| optimum-intel | `support_qwen3_5` branch (editable install) |

---

#### 1. Export (`OVModelForVisualCausalLM`, `image-text-to-text`)

| Field | Result |
|-------|--------|
| Status | **FAIL** |
| Time | 114.3s (model download + tracing attempt) |
| Model ID | `Qwen/Qwen3.5-0.8B` |
| Error | `sdpa_mask_without_vmap() missing 1 required positional argument: 'cache_position'` |

<details>
<summary>Full stacktrace</summary>

```
OVModelForVisualCausalLM.from_pretrained(export=True)
  → main_export() → export_pytorch()
    → TorchScriptPythonDecoder(model, example_input=dummy_inputs)
      → torch.jit.trace(...)
        → patched_forward() [model_patcher.py:8637]
          → self._text_model(...)
            → create_causal_mask() [transformers/masking_utils.py:981]
              → mask_interface = eager_mask_without_vmap [registered at model_patcher.py:278]
                → sdpa_mask_without_vmap(*args, **kwargs) [model_patcher.py:252]
                  → TypeError: missing 'cache_position'
```

</details>

**Root cause:** The transformers masking API changed between 4.53 (which the PR's `model_patcher.py:247` comment references) and 5.3.0.dev0:

| Parameter | Old API (≤ 4.53) | New API (5.3.0.dev0) |
|-----------|-------------------|----------------------|
| 2nd param | `cache_position: torch.Tensor` | `q_length: int` |
| offset | derived from `cache_position[0]` | `q_offset: int` (new kwarg) |

The PR's `eager_mask_without_vmap` (model_patcher.py:249) passes `*args, **kwargs` straight through to `optimum.exporters.onnx.model_patcher.sdpa_mask_without_vmap`, which still expects `cache_position: torch.Tensor` as a required positional parameter. Since transformers 5.3.0 sends `q_length=<int>` as a keyword argument instead, `cache_position` is never provided.

**Note:** transformers' own `sdpa_mask` has backward-compat code (masking_utils.py:486-492) that handles both signatures — the same approach could be applied to `eager_mask_without_vmap` or upstreamed to optimum's `sdpa_mask_without_vmap`.

---

#### 2. CPU Inference

| Field | Result |
|-------|--------|
| Status | SKIP |
| Reason | Blocked by export failure (no IR files produced) |

---

#### 3. GPU Inference (Arc 140V) — Default

| Field | Result |
|-------|--------|
| Status | SKIP |
| Reason | Blocked by export failure |

---

#### 4. GPU Inference (Arc 140V) — `INFERENCE_PRECISION_HINT=f32`

| Field | Result |
|-------|--------|
| Status | SKIP |
| Reason | Blocked by export failure |

---

#### Summary

Export of `Qwen/Qwen3.5-0.8B` via `OVModelForVisualCausalLM.from_pretrained(export=True)` fails during TorchScript tracing due to a signature mismatch between the base branch's `eager_mask_without_vmap` wrapper (pre-existing on `transformers-v5`, not introduced by this PR) and the latest transformers masking API (`q_length`/`q_offset` vs `cache_position`). All inference tests were blocked. The architecture registration itself (`qwen3_5` → `image-text-to-text`, `qwen3_5_text` → `text-generation-with-past`) appears correct and follows the established qwen2_vl/qwen2_5_vl pattern.

**Possible fix:** translate the new kwargs in `eager_mask_without_vmap` before delegating:

```python
def eager_mask_without_vmap(*args, **kwargs) -> Optional[torch.Tensor]:
    kwargs.pop("allow_is_causal_skip", None)
    dtype = kwargs.get("dtype", torch.float32)

    # Bridge new transformers API → old optimum API
    q_length = kwargs.pop("q_length", None)
    q_offset = kwargs.pop("q_offset", 0)
    if q_length is not None and "cache_position" not in kwargs:
        device = kwargs.get("device", "cpu")
        kwargs["cache_position"] = torch.arange(q_offset, q_offset + q_length, device=device)

    mask = sdpa_mask_without_vmap(*args, allow_is_causal_skip=False, **kwargs)
    mask = torch.where(
        mask,
        torch.tensor(0.0, device=mask.device, dtype=dtype),
        torch.tensor(torch.finfo(torch.float16).min, device=mask.device, dtype=dtype),
    )
    return mask
```

**My context:** I'm testing on consumer Intel hardware (Lunar Lake / Arc 140V) and have been contributing NPU-related fixes upstream:
- [npu_compiler#265](https://github.com/openvinotoolkit/npu_compiler/pull/265) / [#266](https://github.com/openvinotoolkit/npu_compiler/pull/266) — VPUX compiler zero-dim guard
- [openvino#34651](https://github.com/openvinotoolkit/openvino/pull/34651) — NPU unbounded dynamic shape guard

Happy to re-test once the masking compat issue is fixed.

---

**AI Usage:** This test plan and report template were developed with AI assistance (Claude Code). All tests were executed by the contributor on real hardware, and all results are empirical observations from actual model export and inference runs.
