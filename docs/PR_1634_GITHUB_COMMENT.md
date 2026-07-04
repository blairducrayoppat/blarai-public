### Test Report: `Qwen/Qwen3.5-0.8B` export on Intel Lunar Lake (Arc 140V)

Tested the `support_qwen3_5` branch with a real `Qwen/Qwen3.5-0.8B` checkpoint on consumer Intel hardware. Export fails during TorchScript tracing due to a masking API signature mismatch between `optimum`'s `sdpa_mask_without_vmap` and transformers 5.3.0.dev0. This is a pre-existing issue on the `transformers-v5` base branch, not introduced by this PR.

---

#### Environment

| Component | Version |
|---|---|
| **Hardware** | Intel Core Ultra 7 258V (Lunar Lake), Arc 140V GPU (16 GB), 32 GB LPDDR5X |
| **OS** | Windows 11 Pro 26200 |
| **Python** | 3.11.9 |
| **OpenVINO** | `2026.0.0-20965-c6d6a13a886` (releases/2026/0) |
| **transformers** | `5.3.0.dev0` (main @ HEAD, 2026-03-12) |
| **optimum-intel** | `support_qwen3_5` branch (editable install from `rkazants/optimum-intel`) |
| **optimum** | installed as dependency (pip, from `optimum-intel[openvino]`) |
| **Devices** | CPU, GPU (Arc 140V), NPU (AI Boost) |

---

#### Results

| Test | Status | Notes |
|---|---|---|
| Export via `OVModelForVisualCausalLM.from_pretrained(export=True)` | **FAIL** | `TypeError` during TorchScript tracing — see below |
| CPU inference | Blocked | No IR produced (export failed) |
| GPU inference (default) | Blocked | No IR produced |
| GPU inference (`INFERENCE_PRECISION_HINT=f32`) | Blocked | No IR produced |

---

#### Failure: `sdpa_mask_without_vmap()` signature mismatch (pre-existing on `transformers-v5`)

**Error:**

```
TypeError: sdpa_mask_without_vmap() missing 1 required positional argument: 'cache_position'
```

**Call chain:**

```
OVModelForVisualCausalLM.from_pretrained(MODEL_ID, export=True)
  → main_export() → export_pytorch()
    → TorchScriptPythonDecoder(model, example_input=dummy_inputs)
      → torch.jit.trace(...)
        → patched_forward()                          # model_patcher.py:8637  [this PR]
          → self._text_model(...)
            → create_causal_mask()                    # transformers/masking_utils.py:981
              → eager_mask_without_vmap()             # model_patcher.py:252  [pre-existing]
                → sdpa_mask_without_vmap(*args, ...)  # optimum/exporters/onnx/model_patcher.py
                  → TypeError: missing 'cache_position'
```

**Root cause:**

The transformers masking API changed between v4.53 (referenced by `model_patcher.py:247` on the `transformers-v5` base branch) and the current transformers `main` (5.3.0.dev0). `create_causal_mask()` now calls the registered mask function with:

```python
mask_interface(batch_size=..., q_length=<int>, kv_length=..., q_offset=<int>, kv_offset=..., ...)
```

But `optimum.exporters.onnx.model_patcher.sdpa_mask_without_vmap` still expects the old signature:

```python
def sdpa_mask_without_vmap(batch_size, cache_position: torch.Tensor, kv_length, kv_offset=0, ...)
```

The base branch's `eager_mask_without_vmap` (model_patcher.py:249) passes `*args, **kwargs` straight through, so `cache_position` is never provided — transformers now sends `q_length` as a keyword argument instead.

**This is not introduced by this PR** — `eager_mask_without_vmap` is unchanged between `transformers-v5` and `support_qwen3_5`. The issue likely affects all VLM exports on the `transformers-v5` branch when paired with transformers >= 5.x.

Note: transformers' own `sdpa_mask` has backward-compat handling at `masking_utils.py:486-492` (detects `torch.Tensor` vs `int`), but the `optimum`-side function does not.

---

#### PR-specific observations

- The Qwen3.5 task registration (`qwen3_5` → `image-text-to-text`, `qwen3_5_text` → `text-generation-with-past`) is correct and follows the established `qwen2_vl` / `qwen2_5_vl` pattern.
- The new code added by this PR (`Qwen3_5ModelPatcher`, `Qwen3_5VisionEmbMergerPatcher`, `RecurrentAttentionCell`, config classes with `Qwen3_5DummyPastKeyValuesGenerator`) all appear structurally sound. I was unable to test runtime behavior due to the export blocker above.
- `MIN_TRANSFORMERS_VERSION = "4.57.0"` is set correctly for the Qwen3.5 config classes.

Happy to re-test once the base-branch masking compat issue is resolved. My hardware is available for GPU/NPU-specific testing if useful.

---

<sub><b>AI usage:</b> Test harness and report developed with AI assistance (Claude Code). All tests executed on real hardware; all results are empirical observations from actual model export runs.</sub>
