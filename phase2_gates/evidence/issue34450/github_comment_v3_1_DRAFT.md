# Issue #34450 — Reproduction Update (OV 2026.0.0)

> Draft v3.1. Supersedes v3 — corrects an over-broad rule-out: per-group INT4 sym
> is the only weight scheme observed to trip NPUW on this IR; channel-wise INT4
> and INT8 both compile through NPUW successfully.

## tl;dr
- On OpenVINO **2026.0.0**, the original SIGABRT now surfaces as a structured Python `RuntimeError` with a clean stack into `npuw/compiled_model.cpp:516`. Failure signature: **`StopLocationVerifierPass: Found 40 duplicated names after full verification`**. Reproducible without the speculative-decoding wrapper — plain `LLMPipeline(ir, "NPU")` is sufficient.
- The IR is structurally valid: same artifact compiles fine on CPU (1.6 s) and GPU (6.9 s). The failure is NPUW-side.
- **The trigger correlates with weight-compression scheme.** Per-group INT4 sym (`group_size=128`, the standard Optimum default) fails NPUW. Channel-wise INT4 (`group_size=-1`) and INT8 both **succeed** through NPUW (\~16-19 s compile). Per-group INT4 asym not yet tested through NPUW.
- The documented "reshape to static shapes" workaround does not apply to optimum-intel stateful LLM IRs — `model.reshape({...})` constrains only the four visible inputs; KV-cache lives in 56 internal `ReadValue`/`Assign` Variables that `reshape()` does not reach.

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

## Core finding — NPUW failure on `LLMPipeline(ir, "NPU")` with per-group INT4 sym

Reproduction is **independent of the speculative-decoding wrapper**. Plain `LLMPipeline(ir, "NPU")` is sufficient. Full Python stack (cell G, IR sha `467f67b1…`):

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

This matches the cause @dmatveev posted on Apr 24. Reproducing without the spec-decode wrapper makes a minimal failing test straightforward to add to the NPUW partitioner suite.

## Quantization-scheme matrix (NPUW)

| Cell | Weight scheme | Export args | NPUW outcome | Compile time |
|---|---|---|---|---|
| G   | per-group INT4 sym | `--weight-format int4 --group-size 128 --ratio 1.0 --sym` | **FAIL** — `StopLocationVerifierPass: 40 duplicated names` | \~6 s to fail |
| G-H | channel-wise INT4  | `--weight-format int4 --group-size -1`                   | **OK** | 19.30 s |
| G-I | INT8               | `--weight-format int8`                                   | **OK** | 16.45 s |
| G-C | per-group INT4 asym (no `--sym`) | `--weight-format int4 --group-size 128 --ratio 1.0` | not yet tested through NPUW | — |

So the NPUW partitioner is producing a name collision specifically for the per-group INT4 sym graph topology, not for INT8 or for channel-wise INT4. That should narrow the search for the duplicated-name source significantly.

## What else the matrix rules in/out

| Hypothesis | Verdict | Evidence |
|---|---|---|
| IR is malformed | Ruled out | Cells D/E: same IR compiles on CPU (1.6 s) and GPU (6.9 s). |
| Failure requires the spec-decode `LLMPipeline(target, "GPU", draft_model=…)` wrapper | Ruled out | Cell G uses plain `LLMPipeline(ir, "NPU")` and reproduces. |
| Reshaping to static shapes (documented NPU workaround) lets the model compile | Ruled out **for stateful IRs** | Cell K: `model.reshape({input_ids:[1,1024], attention_mask:[1,1024], position_ids:[1,1024], beam_idx:[1]})` succeeds — output partial shape becomes `[1,1024,151936]` — but all 56 KV-cache `ReadValue`/`Assign` Variables remain `[?,8,?,128]`. `core.compile_model(model, "NPU")` then still fails with `to_shape was called on a dynamic shape`. The dynamic dims are in the stateful Variables that `Model.reshape({...})` does not address. |

## Reproduction

```bash
# .export-venv: optimum-intel 1.27.0, transformers 4.51.3
optimum-cli export openvino \
  --model Qwen/Qwen3-0.6B-Chat \
  --task text-generation-with-past \
  --weight-format int4 --group-size 128 --ratio 1.0 --sym \
  --trust-remote-code ./qwen3-0.6b-int4-sym-g128

# .venv: openvino-genai 2026.0.0.0, transformers 5.3.0
python -c "
from openvino_genai import LLMPipeline
LLMPipeline('./qwen3-0.6b-int4-sym-g128', 'NPU')
"
```

Swapping `--group-size 128 --sym` for `--group-size -1` (channel-wise INT4) or `--weight-format int8` makes the same code path compile cleanly.

## Artifacts

| Cell | Description | IR `xml` sha256 (prefix) | NPUW outcome |
|---|---|---|---|
| B / G   | per-group INT4 sym (the failing case)        | `467f67b16f9806b0…` | FAIL — `StopLocationVerifierPass` |
| C       | per-group INT4 asym                          | `3b0dd0bb85608d77…` | NPUW not yet tested |
| H / G-H | channel-wise INT4                            | `0628da3f9f23c35b…` | OK (19.30 s) |
| I / G-I | INT8                                         | `6e662ae7ed0e8554…` | OK (16.45 s) |

Per-cell logs, full JSON matrix, and the Cell K reshape probe results can be uploaded if useful.

## Open questions for the OpenVINO team
1. Given the NPUW-side failure is now isolated to per-group INT4 sym on this Qwen3-0.6B IR, would a stripped-down failing test built on this artifact be useful as an NPUW partitioner regression case?
2. Is per-group INT4 asym (cell C) expected to share the failure mode of per-group INT4 sym, or the success path of channel-wise INT4? Happy to run that NPUW cell if it helps narrow the bisect.
3. For stateful LLM IRs that NPUW currently fails to partition, is there a recommended escape hatch on the user side (e.g., an `optimum-cli` flag to expose KV-cache as explicit inputs so `model.reshape()` can fully static-ize the graph), or is fixing NPUW the only path?
