# Issue #34450 — Reproduction Update (OV 2026.0.0)

> Draft v3. Trims previously-noted observations that are documented NPU behavior
> (static-shapes-only limitation) and focuses only on findings the OpenVINO team
> may not already have.

## tl;dr
- On OpenVINO **2026.0.0**, the original SIGABRT now surfaces as a **structured Python `RuntimeError`** with a clean stack trace into `npuw/compiled_model.cpp:516`. Failure signature is **`StopLocationVerifierPass: Found 40 duplicated names after full verification`**. The bug is reproducible without the spec-decode wrapper (plain `LLMPipeline(ir, "NPU")` is sufficient).
- **The IR is structurally valid** — the same artifact compiles fine on CPU (1.6 s) and GPU (6.9 s). The failure is NPUW-side.
- **Quantization scheme is not the trigger.** The same NPUW failure path is reached regardless of weight scheme (per-group INT4 / channel-wise INT4 / INT8).
- **The documented "reshape to static shapes" workaround does not apply** to optimum-intel stateful LLM IRs — `model.reshape({...})` fixes only the four visible inputs; the dynamic dims live in the internal `ReadValue`/`Assign` (KV-cache) Variables, which `reshape()` does not touch.

## Environment

| | Compile-time `.venv` (issue stack) | Export-time `.export-venv` |
|---|---|---|
| openvino | `2026.0.0` | `2026.0.0` |
| openvino-genai | `2026.0.0.0` | — |
| optimum-intel | `1.27.0.dev0+d8864c45` (editable) | `1.27.0` |
| transformers | `5.3.0` | `4.51.3` |
| nncf | `3.0.0` | `3.0.0` |
| torch | `2.10.0` | `2.6.0+cpu` |

Host: Windows 11 Pro 26100, Intel Core Ultra 7 258V (Lunar Lake), Arc 140V GPU, AI Boost NPU driver `32.0.100.4724` (2026-03-18). Two interpreters because `optimum-cli export openvino` requires `transformers<4.58` while the runtime stack ships transformers 5.3.

## Core finding — NPUW failure on `LLMPipeline(ir, "NPU")`

Reproduction is **independent of the speculative-decoding wrapper**: instantiating a plain `LLMPipeline` against the IR and `"NPU"` is sufficient. Full Python stack (cell G, IR sha `467f67b1…`):

```
RuntimeError: Exception from src\inference\src\cpp\core.cpp:113:
Exception from src\inference\src\dev\plugin.cpp:53:
Exception from src\plugins\intel_npu\src\plugin\src\plugin.cpp:879:
Exception from src\plugins\intel_npu\src\compiler_adapter\src\ze_graph_ext_wrappers.cpp:405:
L0 pfnCreate2 result: ZE_RESULT_ERROR_INVALID_NULL_POINTER, code 0x78000007
- pointer argument may not be nullptr . [NPU_VCL] Compiler returned msg:
Exception from src\plugins\intel_npu\src\plugin\npuw\compiled_model.cpp:516:
Failed to compile Model0_kv1152_FCEW000__0 for all devices in [NPU]
Caused by: StopLocationVerifierPass: Found 40 duplicated names after full verification
```

This matches the cause @dmatveev posted on Apr 24. Reproducing it without spec-decode should make a minimal failing test easier to add to the NPUW partitioner suite.

## What the matrix rules out

| Hypothesis | Verdict | Evidence |
|---|---|---|
| IR is malformed | Ruled out | Cells D/E: same IR compiles on CPU (1.6 s) and GPU (6.9 s). |
| INT4 weight-compression scheme is the trigger | Ruled out | Cells H (channel-wise INT4) and I (INT8) reach the same NPU failure path as cell B (per-group INT4). |
| Failure requires the spec-decode `LLMPipeline(target, "GPU", draft_model=…)` wrapper | Ruled out | Cell G uses plain `LLMPipeline(ir, "NPU")` and reproduces. |
| Reshaping to static shapes (documented NPU workaround) lets the model compile | Ruled out for stateful IRs | Cell K: setting all four visible inputs to `[1,1024]` (and `[1,1]`) leaves `all_inputs_static = true` but `core.compile_model(model, "NPU")` still fails with `to_shape was called on a dynamic shape`. The dynamic dims are in the model's internal `ReadValue`/`Assign` (stateful KV cache), not the visible inputs. |

The Cell K result is the one I think is most worth surfacing for the OV team: if NPUW is the only path that handles dynamic stateful-LLM IRs on NPU, then the NPUW failure has no user-side workaround — `Model.reshape()` is not it.

## Reproduction

```bash
# .export-venv: optimum-intel 1.27.0, transformers 4.51.3
optimum-cli export openvino \
  --model Qwen/Qwen3-0.6B-Chat \
  --task text-generation-with-past \
  --weight-format int4 --group-size 128 --ratio 1.0 --sym \
  --trust-remote-code ./qwen3-0.6b-int4

# .venv: openvino-genai 2026.0.0.0, transformers 5.3.0
python -c "
from openvino_genai import LLMPipeline
LLMPipeline('./qwen3-0.6b-int4', 'NPU')
"
```

## Artifacts

| Cell | Description | IR `xml` sha256 (prefix) | Outcome |
|---|---|---|---|
| B | Qwen3-0.6B per-group INT4 sym (`group_size=128`, `ratio=1.0`) | `467f67b16f9806b0…` | Reproduces NPUW failure |
| C | Qwen3-0.6B per-group INT4 asym | `3b0dd0bb85608d77…` | Same path as B |
| H | Qwen3-0.6B channel-wise INT4 (`group_size=-1`) | `0628da3f9f23c35b…` | Same NPU failure path |
| I | Qwen3-0.6B INT8 | `6e662ae7ed0e8554…` | Same NPU failure path |

Per-cell logs, full JSON matrix, and reshape probe results can be uploaded if useful.

## Open questions for the OpenVINO team
1. Is there an existing minimal repro for `StopLocationVerifierPass: Found 40 duplicated names`? If not, would a stripped-down failing test built on this Qwen3-0.6B IR be useful as a regression case?
2. For stateful LLM IRs that NPUW currently fails to partition, is there a recommended escape hatch on the user side (e.g., a flag to expose KV-cache as inputs so `model.reshape()` can fully static-ize the graph), or is fixing NPUW the only path?
3. The `to_shape was called on a dynamic shape` message that comes back from VCL leaks `INT64_MAX`/`INT64_MIN` sentinels in the broadcast error (`'9223372036854775807' and -9223372036854775808'`). Could the front-end translate this into a clearer "NPU requires static shapes; this stateful IR has dynamic KV-cache Variables" diagnostic? Minor UX item, not a blocker.
