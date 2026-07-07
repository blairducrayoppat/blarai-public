# Issue #34450 — Reproduction Update (OV 2026.0.0)

> **Draft v3.3.** Supersedes v3.2.
>
> **What changed vs v3.2:**
>
> 1. **Direct response to @diego-villalobos's reproduction comment.** We hit the
>    *same* `StopLocationVerifierPass: Found 40 duplicated names after full verification`
>    on `Model0_kv1152_FCEW000__0` from the same export command. Same OV 2026.0.0 stack.
>    Diego reports the same error reproduces on OV 2026.1.0 as well, so 2026.1 is unlikely
>    to make the symptom go away.
> 2. **Symmetric INT4 cell ran (cell B-sym).** Result: **OK, NPUW compile 8.58 s**.
>    This refines the trigger: the failure requires **per-group AND asym, both at once**.
>    Either alone (sym per-group, or asym per-channel) compiles fine.
> 3. **NPU usage independently verified** for the three OK NPUW cells (G-H, G-I, G-B-sym)
>    via `OPENVINO_LOG_LEVEL=3` — the verbose stderr dump prints
>    `Model: Stateful LLM model / EXECUTION_DEVICES: NPU / NETWORK_NAME: Model0_prefill`
>    for each. No silent CPU fallback. (Tokenizer + Detokenizer running on CPU is normal
>    OpenVINO GenAI behavior — the LLM model itself is on NPU.)
> 4. **Direct-NPU compile on cell B-sym also fails** with the same
>    `to_shape was called on a dynamic shape` error as the asym cells. So the NPU plugin's
>    dynamic-shape failure (issue #34617, separate from this one) is **scheme-independent**.
>    That matches @YuChern-Intel's earlier statement that "the OpenVINO NPU plugin does
>    not natively support dynamic shapes during inference."

## tl;dr

- We **reproduce @diego-villalobos's exact failure**:
  `StopLocationVerifierPass: Found 40 duplicated names after full verification`
  on `Model0_kv1152_FCEW000__0`, from `optimum-cli export openvino --task
  text-generation-with-past --weight-format int4 --group-size 128 --ratio 1.0` plus
  `LLMPipeline(ir, "NPU")` on OV 2026.0.0. No `as_convolution` / 0-channel diagnostic
  surfaces on this stack — it's the duplicate-name verifier that fails first.
- The IR is structurally valid: same artifact compiles fine on **CPU (1.6 s)** and
  **GPU (6.9 s)**. Failure is in NPUW's partitioning / sub-graph compile path.
- **5-cell NPUW partition matrix**, with EXECUTION_DEVICES verified for the OK cells:

  | Cell    | Export args (delta) | nncf scheme | NPUW outcome |
  |---|---|---|---|
  | G       | `--group-size 128`                   | int4_asym, gs=128       | **FAIL** — StopLocationVerifierPass |
  | G-B-sym | `--group-size 128 --sym`             | **int4_sym**, gs=128    | **OK 8.58 s** (NPU verified) |
  | G-H     | `--group-size -1`                    | int4_asym, per-channel  | **OK 8.38 s** (NPU verified) |
  | G-I     | `--weight-format int8`               | INT8 weight-only         | **OK 8.52 s** (NPU verified) |
  | G-C     | `--group-size 128 --disable-stateful`| (stateless variant)     | **N/A** — fails earlier in StatefulToStateless transformation; `--disable-stateful` is incompatible with `LLMPipeline` |

  **Refined trigger:** the failure requires **per-group AND asym together**.
  Either alone (sym at gs=128, or asym at gs=-1) compiles cleanly through NPUW.
- **Direct `Core().compile_model(ir, "NPU")`** on the same IRs (no NPUW) fails with a
  *different* signature — `to_shape was called on a dynamic shape` at
  `__module.model.layers.0.input_layernorm/aten::mul/Multiply` — and this failure
  is **scheme-independent** (asym, sym, channel-wise, INT8 all hit it). That's the
  documented NPU plugin static-shape limitation, tracked separately as #34617.

## Reconciliation with the issue title

Issue title cites `LLVM ABORT in as_convolution pass — degenerate 0-channel shape`.
Both we and @diego-villalobos see `StopLocationVerifierPass: Found 40 duplicated
names` instead — different MLIR pass, different diagnostic, no `as_convolution` and
no 0-channel tensor diagnostic on OV 2026.0.0. Diego confirms the same is true on
OV 2026.1.0.

We don't claim to know whether (a) the pass pipeline reordered between the original
report's compiler version and 2026.0.0 such that duplicate-name verification trips
first, (b) both diagnostics share a root cause in NPUW partitioning, or (c) they're
distinct bugs with overlapping triggers. If the team can confirm, we'll narrow or
refile accordingly.

## Environment

| | Compile-time `.venv` (issue stack) | Export-time `.export-venv` |
|---|---|---|
| openvino | `2026.0.0` | `2026.0.0` |
| openvino-genai | `2026.0.0.0` | — |
| optimum-intel | `1.27.0.dev0+d8864c45` (editable) | `1.27.0` |
| optimum | `2.1.0.dev0` | `2.1.0` |
| transformers | `5.3.0` | `4.51.3` (matches Intel's recommended pin) |
| nncf | `3.0.0` | `3.0.0` |
| torch | `2.10.0` | `2.6.0+cpu` |

Host: Windows 11 Pro 26100, Intel Core Ultra 7 258V (Lunar Lake), Arc 140V GPU,
AI Boost NPU driver `32.0.100.4724` (2026-03-18).

## Failure stack (cell G — the canonical NPUW failure, identical to Diego's)

```
RuntimeError: Exception from src\inference\src\cpp\core.cpp:113:
Exception from src\inference\src\dev\plugin.cpp:53:
Exception from src\plugins\intel_npu\src\plugin\npuw\compiled_model.cpp:516:
Failed to compile Model0_kv1152_FCEW000__0 for all devices in [NPU]

[ERROR] [vpux-compiler] StopLocationVerifierPass Pass failed :
Found 40 duplicated names after full verification
[ERROR] [vpux-compiler] Failed Pass StopLocationVerifierPass on Operation
loc(fused<{name = "module", type = "Module"}>["module"])
```

Reproduction is independent of the speculative-decoding wrapper — plain
`LLMPipeline(ir, "NPU")` is sufficient. Same submodel name (`Model0_kv1152_FCEW000__0`)
that Diego reports.

## NPU-vs-fallback verification

For each OK cell we ran the harness with `OPENVINO_LOG_LEVEL=3` and confirmed the
LLM submodel landed on NPU. Excerpt from the cell B-sym log
(`cell_g_b_sym_npuw_logged.log`, identical pattern in `cell_g_h_npuw_logged.log`
and `cell_g_i_npuw_logged.log`):

```
Model: Stateful LLM model
  DEVICE_ID:
  ENABLE_CPU_PINNING: NO
  EXECUTION_DEVICES: NPU
  EXECUTION_MODE_HINT: PERFORMANCE
  INFERENCE_PRECISION_HINT: f16
  LOADED_FROM_CACHE: NO
  MODEL_PRIORITY: MEDIUM
  NETWORK_NAME: Model0_prefill
  ...
EXECUTION_DEVICES:
 NPU: Intel(R) AI Boost
```

The OV Tokenizer and OV Detokenizer submodels run on CPU
(`EXECUTION_DEVICES: CPU`); that is the normal OpenVINO GenAI split, not silent
fallback. So the OK results genuinely exercise NPU compilation — the per-group
+ asym path is the only one that fails partition.

## Direct NPU plugin failure (separate, not the NPUW bug — relevant to #34617)

To make sure we don't conflate the NPUW partition bug with the NPU plugin
dynamic-shape limitation, we also ran direct `Core().compile_model(ir, "NPU")`
(no NPUW) against every cell. All five (asym per-group, sym per-group,
channel-wise, INT8, even cell B-sym) fail with the *same* signature at
`__module.model.layers.0.input_layernorm/aten::mul/Multiply`:

```
[ERROR] [vpux-compiler] Got Diagnostic at loc(fused<{name = ".../Multiply", type = "Multiply"}>) :
  Got non broadcastable dimensions pair :
  '9223372036854775807' and -9223372036854775808'
RuntimeError: ...
  Exception from src\core\src\partial_shape.cpp:266:
  to_shape was called on a dynamic shape.
```

This is **scheme-independent** — the dynamic-shape failure happens regardless of
weight format. That matches @YuChern-Intel's earlier observation that "the OpenVINO
NPU plugin does not natively support dynamic shapes during inference." Logged here
only so the two failure modes don't get confused; this is the issue #34617 territory,
not this issue.

We also confirmed (cell K) that `Model.reshape({input_ids, attention_mask,
position_ids, beam_idx})` is **not** sufficient to static-ize an optimum-intel
stateful LLM IR — it constrains only the four visible inputs; the 56 internal
KV-cache `ReadValue`/`Assign` Variables remain `[?,8,?,128]`, and the direct-NPU
compile still fails at the same Multiply node.

## What the matrix rules in/out

| Hypothesis | Verdict | Evidence |
|---|---|---|
| IR is malformed | Ruled out | Cells D/E: same IR (cell_b) compiles on CPU (1.6 s) and GPU (6.9 s). |
| Failure requires the spec-decode `LLMPipeline(target, "GPU", draft_model=…)` wrapper | Ruled out | Cell G uses plain `LLMPipeline(ir, "NPU")` and reproduces. |
| Failure requires asym (any weight layout) | Ruled out | Cell G-H: asym + channel-wise → OK. |
| Failure requires per-group (any sym setting) | Ruled out | Cell G-B-sym: sym + per-group → OK. |
| Failure is silent CPU/GPU fallback masking NPU compile | Ruled out | OPENVINO_LOG_LEVEL=3 prints `Model: Stateful LLM model / EXECUTION_DEVICES: NPU` for all OK cells. |
| `Model.reshape({...})` is sufficient to static-ize a stateful LLM IR | Ruled out for stateful IRs | Cell K: only the 4 visible inputs reshape; KV-cache Variables stay dynamic; NPU still fails. |
| `NPU_COMPILER_TYPE=MLIR` is a valid escape hatch | Ruled out | Cell J1: rejected as `Value 'MLIR' is not a valid COMPILER_TYPE option` on OV 2026.0.0 (only `DRIVER` and `PLUGIN` accepted). |
| `NPU_COMPILER_TYPE=DRIVER` changes the direct-compile failure | Ruled out | Cell J2: same `to_shape was called on a dynamic shape`. |

## Reproduction (minimal, matches Diego's)

```bash
# Export venv: optimum-intel 1.27.0, optimum 2.1.0, transformers 4.51.3, nncf 3.0.0
optimum-cli export openvino \
  --model Qwen/Qwen3-0.6B \
  --task text-generation-with-past \
  --weight-format int4 --group-size 128 --ratio 1.0 \
  ./qwen3-0.6b-int4-asym-g128

# Runtime venv: openvino 2026.0.0, openvino-genai 2026.0.0.0
python -c "
from openvino_genai import LLMPipeline
LLMPipeline('./qwen3-0.6b-int4-asym-g128', 'NPU')
"
```

To make the failure go away while staying close to the documented NPU LLM recipe,
add `--sym`:

```bash
optimum-cli export openvino \
  --model Qwen/Qwen3-0.6B \
  --task text-generation-with-past \
  --weight-format int4 --group-size 128 --ratio 1.0 --sym \
  ./qwen3-0.6b-int4-sym-g128
```

`LLMPipeline(ir, "NPU")` then compiles in \~8.5 s on real NPU. Same is true if you
keep asym but switch to channel-wise (`--group-size -1`) or to `--weight-format int8`.

## Artifacts

| Cell    | Description                                  | NPUW outcome                  |
|---|---|---|
| B / G   | per-group INT4 **asym**                      | FAIL — StopLocationVerifierPass |
| **B-sym / G-B-sym** | **per-group INT4 sym**           | **OK 8.58 s (NPU verified)**  |
| H / G-H | channel-wise INT4 asym                       | OK 8.38 s (NPU verified)      |
| I / G-I | INT8 weight-only                             | OK 8.52 s (NPU verified)      |
| C / G-C | per-group INT4 asym + `--disable-stateful`   | N/A — fails before NPUW       |
| K       | per-group INT4 asym + `Model.reshape({...})` | direct-NPU still fails (KV-cache Variables stay dynamic) |

Per-cell logs (`cell_<id>_export.log`, `cell_<id>_npuw[_logged].log`,
`cell_<id>_direct.log`), full JSON matrix (`compile_matrix.json`), and the
`OPENVINO_LOG_LEVEL=3` device-attribution dumps are available on request.

## Open questions for the team

1. **Same root cause as the issue title?** Are
   `StopLocationVerifierPass: 40 duplicated names` (what Diego and we both observe
   on 2026.0.0 / 2026.1.0) and
   `LLVM ABORT in as_convolution pass — degenerate 0-channel shape` (the title)
   the same root cause? If yes, this issue covers both. If no, we should refile
   the duplicate-name failure separately.
2. **Why per-group + asym specifically?** The fact that flipping *either* axis
   (`--sym`, or `--group-size -1`) fixes it suggests the duplicate-name source is
   in a code path that the NPUW partitioner only takes for per-group + asym
   weight decompositions (where each group has its own `zero_point`/`scale`). Is
   there a known canonicalization in NPUW that names ZP/scale subgraphs in a way
   that collides 40 times for a 28-layer model with 4 attention sub-projections?
3. **Stateful escape hatch.** Is there a recommended user-side workaround for
   stateful LLM IRs that NPUW can't partition (e.g., an `optimum-cli` flag to
   expose KV-cache as explicit inputs so `Model.reshape` reaches them), or is
   fixing NPUW the only path? `--disable-stateful` is not viable —
   `LLMPipeline` requires a stateful model with `beam_idx`.

Happy to share the IRs, the export venv lockfile, or the verbose log dumps if any
of those would help triangulate.

---

## Status of this draft

**NOT YET POSTED.** Awaiting Lead Architect approval. All five open items from v3.2
are now resolved:

- [x] Symmetric INT4 cell exported and tested (OK)
- [x] `EXECUTION_DEVICES` query / OPENVINO_LOG_LEVEL=3 verification on OK cells (NPU confirmed)
- [x] Direct-NPU sym test (also fails dynamic-shape — scheme-independent)
- [x] Reconciliation with @diego-villalobos's comment
- [x] Refined trigger condition documented (per-group AND asym)

No GitHub posting will happen without your explicit go-ahead.
