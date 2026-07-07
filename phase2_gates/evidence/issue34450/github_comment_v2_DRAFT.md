## Independent reproduction with extended export × device × compile-mode matrix

Hi @diego-villalobos / OpenVINO team — confirming your Apr 24 finding from a
separate Lunar Lake host and extending the analysis with an 11-cell matrix
(A–C exporter sweep + D–J device/compile-mode sweep) designed to isolate
exporter, weight-format, NPUW vs raw NPU plugin, and `NPU_COMPILER_TYPE`.

The matrix surfaces **two distinct NPU compile failures** for Qwen3-0.6B
INT4 — see the Summary Matrix below.

### Environment

| Field | Issue post (Mar 2026) | This reproduction (compile-time `.venv`) | Export-time `.export-venv` |
|---|---|---|---|
| OpenVINO | `2026.0.0-20965` | `2026.0.0` ✅ | `2026.0.0` |
| OpenVINO GenAI | `2026.0.0.0-2820` | `2026.0.0.0` ✅ | n/a |
| optimum-intel | `1.27.0` | `1.27.0.dev0+d8864c45` (editable) | `1.27.0` ✅ |
| optimum | n/a | `2.1.0.dev0` | `2.1.0` |
| transformers | `4.51.3` | `5.3.0` | `4.51.3` ✅ |
| nncf | `3.0.0` | `3.0.0` ✅ | `3.0.0` ✅ |
| torch | n/a | `2.10.0` | `2.6.0+cpu` |
| Host | LNL | Intel Core Ultra 7 258V (LNL), Windows 11 | same |
| GPU driver | `32.0.101.6987` | `32.0.101.8735` (4/19/2026, **newer**) | — |
| NPU driver | `32.0.100.4514` | `32.0.100.4724` (3/18/2026, **newer**) | — |

Exports were produced in a dedicated `.export-venv` pinned to the issue's
**exact** stack (`optimum-intel 1.27.0` / `transformers 4.51.3` / `nncf 3.0.0`)
to eliminate exporter-version drift as a confound. Compile cells run in
the runtime `.venv` (`openvino-genai 2026.0.0.0`).

### Summary matrix (Qwen3-0.6B)

Two independent matrices — exporter sweep (A–C) and compile sweep (D–J) — all
against the same model `Qwen/Qwen3-0.6B`.

| Cell | IR (export) | Device | Compile mode / config | Outcome | Failure signature (truncated) |
|---|---|---|---|---|---|
| A | `int4 g=128 r=1.0` (no `--task`, stateful) | NPU | `LLMPipeline(target=Qwen3-14B/GPU, draft=Qwen3-0.6B/NPU)` | ❌ | `StopLocationVerifierPass: Found 40 duplicated names` |
| B | `int4 g=128 r=1.0 --task text-generation-with-past` (stateful, **issue command**) | NPU | spec-decode draft, as A | ❌ | `StopLocationVerifierPass: Found 40 duplicated names` |
| C | B + `--disable-stateful` | NPU | spec-decode draft, as A | ❌ | `Stateful models without 'beam_idx' input are not supported in StatefulToStateless transformation` |
| **D** | Cell B IR | **CPU** | `core.compile_model(...)` direct | ✅ **ok** (1.56 s) | — |
| **E** | Cell B IR | **GPU** | `core.compile_model(...)` direct | ✅ **ok** (6.92 s) | — |
| **F** | Cell B IR | NPU | `core.compile_model(..., "NPU")` **direct, no NPUW** | ❌ | `to_shape was called on a dynamic shape` + `Got non broadcastable dimensions pair: '9223372036854775807' and -9223372036854775808'` |
| **G** | Cell B IR | NPU | `LLMPipeline(ir, "NPU")` (NPUW, no spec-decode wrapper) | ❌ | `StopLocationVerifierPass: Found 40 duplicated names` (same as A/B) |
| **H** | `int4 g=-1 r=1.0` (channel-wise INT4) | NPU | direct, no NPUW | ❌ | identical to F (`to_shape was called on a dynamic shape`) |
| **I** | `int8` | NPU | direct, no NPUW | ❌ | identical to F (`to_shape was called on a dynamic shape`) |
| **J1** | Cell B IR | NPU | direct + `NPU_COMPILER_TYPE=MLIR` | ❌ | `Value 'MLIR' is not a valid COMPILER_TYPE option` (option removed in 2026.0.0?) |
| **J2** | Cell B IR | NPU | direct + `NPU_COMPILER_TYPE=DRIVER` | ❌ | identical to F (DRIVER is the default) |

### Key findings

1. **Two distinct NPU compile failure modes** are surfaced by the matrix —
   they sit on different code paths and almost certainly need to be filed
   (or at least diagnosed) separately:

   - **Direct NPU plugin path (F / H / I / J2)** — fails in the front-end
     before NPUW with `to_shape was called on a dynamic shape` and a
     downstream `[NPU_VCL] Compiler returned msg: Got non broadcastable
     dimensions pair: '9223372036854775807' and -9223372036854775808'`.
     The `INT64_MAX` / `INT64_MIN` sentinels strongly suggest the
     dynamic-axis upper-bound resolver is reading uninitialized memory
     or is hitting an unbounded-dim path that should have been bounded
     by reshape.
   - **NPUW / `LLMPipeline` path (A / B / G)** — gets past the front-end,
     reaches the NPUW partitioner, and dies in
     `npuw/compiled_model.cpp:516` with
     `StopLocationVerifierPass: Found 40 duplicated names`. This matches
     your Apr 24 observation exactly.

2. **The IR is structurally valid** — Cells D (CPU) and E (GPU) compile
   the same Cell B IR successfully in 1.6 s and 6.9 s respectively. So
   the failures in F–J are NPU-plugin-side, not exporter-side.

3. **Quantization scheme is not the cause.** Per-group INT4 (B/F),
   channel-wise INT4 (H), and INT8 (I) all fail the direct-NPU path
   with the **identical** `to_shape was called on a dynamic shape`
   signature. So neither the INT4 quantization nor the per-group layout
   produces the dynamic-shape failure — it is structural to the model
   shape on this NPU plugin / driver pair.

4. **`NPU_COMPILER_TYPE=MLIR` is no longer accepted in OV 2026.0.0**
   (J1: `Value 'MLIR' is not a valid COMPILER_TYPE option`). Only
   `DRIVER` is accepted, and `DRIVER` is the default — so this knob
   provides no workaround on 2026.0.0.

5. **Cell B reproduces the NPUW failure with the exact issue stack**
   (optimum-intel `1.27.0`, transformers `4.51.3`, nncf `3.0.0`) — so
   the NPUW/`StopLocationVerifierPass` bug is not exporter-version
   drift. Combined with G (Cell B IR re-loaded under `LLMPipeline(NPU)`
   without any spec-decode wrapper) reproducing the same failure, the
   bug is reachable from any caller that goes through NPUW for this
   model + INT4 layout.

6. **Original SIGABRT is gone.** All eleven cells now fail with clean
   Python `RuntimeError`s — the crash has been converted to a
   structured error since #34450 was originally filed.

### Failure signatures (grep-ready)

**Direct NPU plugin path (F / H / I / J2):**

```
[ERROR] [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node
'__module.model.embed_tokens/ov_ext::embedding/Convert_1' (type 'Convert'):
input '0' bounds are '[9223372036854775807, 9223372036854775807]'
[ERROR] [vpux-compiler] Got Diagnostic at loc(fused<{name =
"__module.model.layers.0.input_layernorm/aten::mul/Multiply", type = "Multiply"}>...]) :
Got non broadcastable dimensions pair : '9223372036854775807' and -9223372036854775808'
RuntimeError: ... Exception from src\plugins\intel_npu\src\compiler_adapter\src\ze_graph_ext_wrappers.cpp:405:
L0 pfnCreate2 result: ZE_RESULT_ERROR_INVALID_NULL_POINTER, code 0x78000007 - pointer argument may not be nullptr.
[NPU_VCL] Compiler returned msg: Exception from src\core\src\partial_shape.cpp:266:
to_shape was called on a dynamic shape.
```

**NPUW / `LLMPipeline` path (A / B / G):**

```
[ERROR] [vpux-compiler] Got Diagnostic at loc(fused<{name = "module", type = "Module"}>["module"]) :
StopLocationVerifierPass Pass failed : Found 40 duplicated names after full verification
[ERROR] [vpux-compiler] Failed Pass StopLocationVerifierPass on Operation
loc(fused<{name = "module", type = "Module"}>["module"])
RuntimeError: ... Exception from src\plugins\intel_npu\src\plugin\npuw\compiled_model.cpp:516:
Failed to compile Model0_kv1152_FCEW000__0 for all devices in [NPU]
```

### Provenance (sha256, IR, logs)

| Cell | `openvino_model.xml` sha256 | `openvino_model.bin` sha256 |
|---|---|---|
| A (cell_a) | (n/a — no `--task`, see prior comment for sha) | — |
| B / D / E / G / J1 / J2 (cell_b) | `467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7` | `0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af` |
| C (cell_c) | (see prior comment) | — |
| H (cell_h, channel-wise INT4) | `0628da3f9f23c35b95908a7cdab666b4a72785c62dced0fcb1e6f64d94b7dc7d` | `7c6aff87c19938037fc1642d701c32b567ddbc3a957b021feb722a6cab0265f5` |
| I (cell_i, INT8) | `6e662ae7ed0e855460c939d266f52b3b7383e2535a717c2cb13da4bc19324f20` | `2ac6e241235fd70e110ae90771ffc9ec8ff11de70ab6f17992d574e156654a73` |

Per-cell command lines, full stderr/log tails, and the machine-readable
matrix (`compile_matrix.json`, `compile_matrix.md`) are available on
request.

### Open questions for the team

1. Are F/H/I/J2 (`to_shape was called on a dynamic shape` from the front-end)
   already tracked as a separate issue, or do they belong on this thread?
   The signature looks distinct from #34450's NPUW failure but both block
   the same model from running on NPU.

2. Is `NPU_COMPILER_TYPE=MLIR` deliberately removed in 2026.0.0, or is the
   option name renamed? If removed, would a 2026.1.0 / nightly with the
   MLIR backend re-enabled produce a different result for cell B?

3. Happy to re-run with any specific `--ov-config` overrides, additional
   `NPU_*` flags, or against a nightly build — the matrix harness is
   factored to add cells trivially.
