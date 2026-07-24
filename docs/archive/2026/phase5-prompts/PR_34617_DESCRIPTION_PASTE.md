---
title: PR_34617_DESCRIPTION_PASTE
status: archived
area: portfolio
---

### Details:
- Adds early validation in `Plugin::compile_model()` to detect models with unbounded dynamic dimensions (upper bound = `INT64_MAX`) before they reach the VPUX compiler.
- **Problem**: When a model has dimensions with `INT64_MAX` upper bounds (common in LLM exports via `optimum-cli`), the NPU plugin passes the serialized IR through to the VPUX compiler via the L0 API (`pfnCreate2`). The compiler's broadcast/shape analysis encounters `INT64_MAX` values, causing signed-integer overflow and cascading failures:
  ```
  User code: core.compile_model(model, "NPU")
    → plugin.cpp :: Plugin::compile_model()
      → DriverCompilerAdapter::compile()
        → ze_graph_ext_wrappers.cpp :: getGraphDescriptor()
          → L0 API: pfnCreate2
            → VPUX compiler: signed overflow in broadcast analysis
            → "to_shape was called on a dynamic shape"
  ```
- The existing internal option `NPU_DYNAMIC_SHAPE_TO_STATIC` does not help — it would apply `INT64_MAX` as a static dimension, which is meaningless.
- **Fix**: \~25-line guard inserted after batch handling (which may resolve batch-axis dynamics) and before `compiler->compile()`. It checks parameters and results for dimensions where `dim.get_interval().has_upper_bound()` returns `false`, and throws an actionable error message directing users to `model.reshape()`.
- **Error message improvement**:
  Before: `RuntimeError: to_shape was called on a dynamic shape.`
  After:
  ```
  RuntimeError: NPU does not support models with unbounded dynamic dimensions.
  Parameter 'input_ids' has dimension [1] with no finite upper bound (upper bound
  is INT64_MAX). Please reshape the model to use static shapes before compiling
  for the NPU device:
      model.reshape({<static_shape>})
  See: https://docs.openvino.ai/2025/openvino-workflow/running-inference/changing-input-shape.html
  ```
- **Regression risk**: Zero. This guard only rejects models that already fail with a confusing error. Does not affect models with static shapes, bounded dynamic shapes, or the `DYNAMIC_SHAPE_TO_STATIC` path.
- All APIs used (`model->is_dynamic()`, `get_parameters()`, `get_partial_shape()`, `dim.get_interval().has_upper_bound()`, `OPENVINO_THROW()`) are existing public OpenVINO C++ APIs already used elsewhere in `plugin.cpp`.

### Tickets:
- Closes #34617 — NPU `compile_model` fails with "to_shape was called on a dynamic shape" for Qwen3-0.6B INT4
- Related #32466 — SenseVoice NPU compile fails with same `INT64_MAX` error (same root cause)
- Related #24619 — `to_shape` on dynamic shape (NPU)
- Related #26375, #26357 — NPU dynamic shape compilation errors

### AI Assistance:
- AI assistance used: yes
- AI (GitHub Copilot) was used for: source code analysis to trace the error chain through the NPU compile path, generating the guard clause implementation, and drafting the PR description and commit message.
- Human validation: All code was reviewed and validated by the contributor. The fix logic and insertion point were determined through manual analysis of 10+ source files in the NPU plugin. Build/test validation performed locally on Intel Core Ultra 7 258V with NPU 4000.
