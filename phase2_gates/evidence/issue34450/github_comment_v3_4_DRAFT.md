# Issue #34450 — Reproduction Update (OV 2026.0.0)

> **Draft v3.4.** Supersedes v3.3.
>
> **What changed vs v3.3 (audit pass — two material corrections):**
>
> 1. **End-to-end `generate()` now run on every "OK" cell.** v3.3 only verified
>    that the OK cells *constructed* successfully — the verbose log only ever
>    surfaces the prefill submodel (`Model0_prefill`). After actually calling
>    `pipe.generate(prompt, max_new_tokens=16)`:
>    - **Cell B-sym (per-group sym INT4)**: generates 16 tokens in 0.97 s. ✓
>    - **Cell H (channel-wise asym INT4)**: generates 16 tokens in 2.80 s. ✓
>    - **Cell I (INT8 weight-only)**: **CRASHES with Windows access violation
>      `0xC0000005` (exit -1073741819) inside the first `generate()` call.**
>      Construct succeeded; decode does not. v3.3's "INT8 OK" claim was wrong —
>      it covered construct only. This may be a **separate bug** unrelated to
>      the duplicate-name failure; we flag it here and can refile if you'd
>      like a dedicated issue.
> 2. **The failing config is outside Intel's *documented* NPU LLM recipe.** The
>    [official OpenVINO NPU GenAI page](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html)
>    explicitly states LLMs **must** be exported with **`--sym`**, 4-bit weight
>    format, channel-wise or group-wise quantization, and `--ratio 1.0`. The
>    failing command (Diego's, the original report's, ours) omits `--sym`, so
>    per-group **asym** INT4 is not in Intel's documented support matrix. We
>    still consider the failure worth reporting because (a) the diagnostic
>    (`StopLocationVerifierPass`) is opaque rather than a clean "configuration
>    not supported on NPU" rejection, and (b) the path through NPUW that the
>    duplicate-name failure exposes may also affect supported configs under
>    other triggers (e.g., longer `MAX_PROMPT_LEN` engaging the same chunked
>    prefill submodel — see Open Question 2 below).
>
> **Carried forward from v3.3:**
>
> - Reproduces @diego-villalobos's exact `StopLocationVerifierPass: Found 40
>   duplicated names after full verification` on `Model0_kv1152_FCEW000__0`.
> - Direct-NPU compile fails *scheme-independently* with the dynamic-shape
>   `to_shape was called on a dynamic shape` error (issue #34617 territory,
>   not this issue).
> - `Model.reshape({...})` is not sufficient to static-ize a stateful LLM IR
>   (KV-cache `ReadValue`/`Assign` Variables remain dynamic).

## tl;dr

- We **reproduce @diego-villalobos's exact failure**:
  `StopLocationVerifierPass: Found 40 duplicated names after full verification`
  on `Model0_kv1152_FCEW000__0`, from `optimum-cli export openvino --task
  text-generation-with-past --weight-format int4 --group-size 128 --ratio 1.0`
  plus `LLMPipeline(ir, "NPU")` on OV 2026.0.0. No `as_convolution` /
  0-channel diagnostic surfaces on this stack — it's the duplicate-name
  verifier that fails first.
- The IR is structurally valid: same artifact compiles fine on **CPU (1.6 s)**
  and **GPU (6.9 s)**. Failure is in NPUW's partitioning / sub-graph compile
  path.
- **5-cell NPUW partition matrix**, with end-to-end `generate()` verified for
  the OK cells:

  | Cell    | Export args (delta) | nncf scheme | Construct | `generate(16 tok)` |
  |---|---|---|---|---|
  | G       | `--group-size 128`                   | int4_asym, gs=128       | **FAIL** — StopLocationVerifierPass | n/a |
  | G-B-sym | `--group-size 128 --sym`             | **int4_sym**, gs=128    | OK 8.58 s                            | **OK 0.97 s, 16 tok ✓** |
  | G-H     | `--group-size -1`                    | int4_asym, per-channel  | OK 8.38 s                            | **OK 2.80 s, 16 tok ✓** |
  | G-I     | `--weight-format int8`               | INT8 weight-only         | OK 8.52 s                            | **CRASH 0xC0000005 (access violation)** |
  | G-C     | `--group-size 128 --disable-stateful`| (stateless variant)     | N/A — fails earlier in StatefulToStateless transformation; `--disable-stateful` is incompatible with `LLMPipeline` | n/a |

  **Trigger for THIS issue (the StopLocationVerifierPass failure):** per-group
  **asym** INT4. Per-group sym (Intel's documented recipe) and channel-wise
  asym both compile and generate cleanly on NPU. Per-group sym matches Intel's
  documented requirement; channel-wise asym is undocumented but happens to
  work end-to-end.

  **Separate observation:** INT8 weight-only constructs but crashes during the
  first `generate()` call. We can file separately on request.

## Relationship to Intel's documented NPU LLM recipe

The [official OpenVINO 2026 NPU GenAI page](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html)
states:

> *LLMs must be exported with the following settings:*
> - *Symmetric weights compression: `--sym`;*
> - *4-bit weight format (INT4 or NF4);*
> - *Channel-wise or group-wise weight quantization: `--group-size -1` or `--group-size 128`;*
> - *Maximize the 4-bit weight ratio: `--ratio 1.0`.*

The original report's command and Diego's reproduction command both omit
`--sym`. Per the docs, that combination is not in the supported NPU LLM
matrix. If Intel's intent is to *reject* per-group asym with a clean
configuration error rather than fail in `StopLocationVerifierPass` deep in
the partitioner, that would be a strictly better user experience than the
current opaque failure — and it would also remove the chance that this same
NPUW code path bites someone using a *supported* config under a different
trigger.

## Reconciliation with the issue title

Issue title cites `LLVM ABORT in as_convolution pass — degenerate 0-channel
shape`. Both we and @diego-villalobos see `StopLocationVerifierPass: Found 40
duplicated names` instead — different MLIR pass, different diagnostic, no
`as_convolution` and no 0-channel tensor diagnostic on OV 2026.0.0. Diego
confirms the same is true on OV 2026.1.0.

We don't claim to know whether (a) the pass pipeline reordered between the
original report's compiler version and 2026.0.0 such that duplicate-name
verification trips first, (b) both diagnostics share a root cause in NPUW
partitioning, or (c) they're distinct bugs with overlapping triggers. If the
team can confirm, we'll narrow or refile accordingly.

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

Host: Windows 11 Pro 26100, Intel Core Ultra 7 258V (Lunar Lake), Arc 140V
GPU, AI Boost NPU driver `32.0.100.4724` (2026-03-18). No OV compiler cache
present (`%LOCALAPPDATA%\openvino_cache` does not exist; runs are cold-compile).

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
`LLMPipeline(ir, "NPU")` is sufficient. Same submodel name
(`Model0_kv1152_FCEW000__0`) that Diego reports.

The submodel name is informative: `kv1152` matches `MAX_PROMPT_LEN` (1024
default) + `MIN_RESPONSE_LEN` (128 default) = 1152, which is the KV-cache size
for the dynamic chunked-prefill submodel introduced for NPUW LLMs in OV 2025.3
(`PREFILL_HINT: DYNAMIC` is the default). The OK cells, by contrast, only
expose `Model0_prefill` in their verbose logs — see Open Question 2 below.

## NPU-vs-fallback verification (now extended to end-to-end generate)

For each OK cell we ran the harness with `OPENVINO_LOG_LEVEL=3` and confirmed
the LLM submodel landed on NPU, then called `pipe.generate(...)` to exercise
the decode path. Cell B-sym excerpt
(`cell_g_b_sym_npuw_logged.log` for construct, `cell_b_sym_e2e.log` for
end-to-end):

```
Model: Stateful LLM model
  EXECUTION_DEVICES: NPU
  INFERENCE_PRECISION_HINT: f16
  LOADED_FROM_CACHE: NO
  NETWORK_NAME: Model0_prefill
EXECUTION_DEVICES:
 NPU: Intel(R) AI Boost
GENERATE_OK tokens=16 elapsed=0.97s output='<think> | Okay, so the user is asking, "The capital of France is'
```

Cell H end-to-end (`cell_h_e2e.log`): `GENERATE_OK tokens=16 elapsed=2.80s
output="<think> | Okay, let's see. The user is asking about the capital of"`.

Cell I (`cell_i_e2e.log`) constructs but exits `-1073741819` (Windows
`STATUS_ACCESS_VIOLATION` `0xC0000005`) during the first `generate()` call. No
Python traceback — native crash.

So OK cells G-B-sym and G-H genuinely exercise NPU end-to-end. OK cell G-I
covers construct only and should be considered a **separate decode-time
failure**, not a clean "INT8 works on NPU" data point.

The OV Tokenizer and OV Detokenizer submodels run on CPU
(`EXECUTION_DEVICES: CPU`); that is the normal OpenVINO GenAI split, not
silent fallback.

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

This is **scheme-independent** — the dynamic-shape failure happens regardless
of weight format. That matches @YuChern-Intel's earlier observation that
"the OpenVINO NPU plugin does not natively support dynamic shapes during
inference." Logged here only so the two failure modes don't get confused;
this is the issue #34617 territory, not this issue.

We also confirmed (cell K) that `Model.reshape({input_ids, attention_mask,
position_ids, beam_idx})` is **not** sufficient to static-ize an
optimum-intel stateful LLM IR — it constrains only the four visible inputs;
the 56 internal KV-cache `ReadValue`/`Assign` Variables remain `[?,8,?,128]`,
and the direct-NPU compile still fails at the same Multiply node.

## What the matrix rules in/out

| Hypothesis | Verdict | Evidence |
|---|---|---|
| IR is malformed | Ruled out | Cells D/E: same IR (cell_b) compiles on CPU (1.6 s) and GPU (6.9 s). |
| Failure requires the spec-decode `LLMPipeline(target, "GPU", draft_model=…)` wrapper | Ruled out | Cell G uses plain `LLMPipeline(ir, "NPU")` and reproduces. |
| Failure requires asym (any weight layout) | Ruled out | Cell G-H: asym + channel-wise → constructs and generates 16 tokens on NPU. |
| Failure requires per-group (any sym setting) | Ruled out | Cell G-B-sym: sym + per-group → constructs and generates 16 tokens on NPU. |
| Failure is silent CPU/GPU fallback masking NPU compile | Ruled out | OPENVINO_LOG_LEVEL=3 + end-to-end `generate()` on cells B-sym and H confirm NPU. |
| `Model.reshape({...})` is sufficient to static-ize a stateful LLM IR | Ruled out for stateful IRs | Cell K: only the 4 visible inputs reshape; KV-cache Variables stay dynamic; NPU still fails. |
| `NPU_COMPILER_TYPE=MLIR` is a valid escape hatch | Ruled out | Cell J1: rejected as `Value 'MLIR' is not a valid COMPILER_TYPE option` on OV 2026.0.0 (only `DRIVER` and `PLUGIN` accepted). |
| `NPU_COMPILER_TYPE=DRIVER` changes the direct-compile failure | Ruled out | Cell J2: same `to_shape was called on a dynamic shape`. |
| INT8 weight-only is a clean alternative on NPU | **NOT supported by our data** | Cell G-I: constructs OK, but first `generate()` crashes with `STATUS_ACCESS_VIOLATION`. Possibly a separate bug. |

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

To make the failure go away **and** match Intel's documented NPU LLM recipe,
add `--sym`:

```bash
optimum-cli export openvino \
  --model Qwen/Qwen3-0.6B \
  --task text-generation-with-past \
  --weight-format int4 --group-size 128 --ratio 1.0 --sym \
  ./qwen3-0.6b-int4-sym-g128
```

`LLMPipeline(ir, "NPU")` then compiles in \~8.5 s on real NPU and generates
end-to-end (`pipe.generate("The capital of France is", max_new_tokens=16)`
returns sensible Qwen3 output in \~1 s).

Channel-wise asym (`--group-size -1`) also works end-to-end on NPU even
though it's not in Intel's documented recipe. INT8 weight-only constructs
but does not survive the first `generate()` call (see "separate observation"
above).

## Artifacts

| Cell    | Description                                  | Construct | End-to-end `generate(16)` |
|---|---|---|---|
| B / G   | per-group INT4 **asym**                      | FAIL — StopLocationVerifierPass | n/a |
| **B-sym / G-B-sym** | **per-group INT4 sym**           | **OK 8.58 s** | **OK 0.97 s, sensible output** |
| H / G-H | channel-wise INT4 asym                       | OK 8.38 s | OK 2.80 s, sensible output |
| I / G-I | INT8 weight-only                             | OK 8.52 s | **CRASH 0xC0000005 access violation** |
| C / G-C | per-group INT4 asym + `--disable-stateful`   | N/A — fails before NPUW | n/a |
| K       | per-group INT4 asym + `Model.reshape({...})` | direct-NPU still fails (KV-cache Variables stay dynamic) | n/a |

Per-cell logs (`cell_<id>_export.log`, `cell_<id>_npuw[_logged].log`,
`cell_<id>_direct.log`, **`cell_<id>_e2e.log`**), full JSON matrix
(`compile_matrix.json`), and the `OPENVINO_LOG_LEVEL=3` device-attribution
dumps are available on request.

## Open questions for the team

1. **Same root cause as the issue title?** Are
   `StopLocationVerifierPass: 40 duplicated names` (what Diego and we both
   observe on 2026.0.0 / 2026.1.0) and
   `LLVM ABORT in as_convolution pass — degenerate 0-channel shape` (the
   title) the same root cause? If yes, this issue covers both. If no, we
   should refile the duplicate-name failure separately.
2. **Is the trigger really "per-group + asym," or is it the chunked
   dynamic-prefill code path that per-group + asym happens to activate?** The
   failing submodel is `Model0_kv1152_FCEW000__0` — `kv1152` =
   `MAX_PROMPT_LEN`(1024) + `MIN_RESPONSE_LEN`(128), the dynamic chunked
   prefill submodel from OV 2025.3+. The OK cells (B-sym, H) never expose
   this submodel name in their verbose logs — only `Model0_prefill`. If
   per-group + asym is what triggers chunked-prefill partitioning while sym /
   channel-wise stays on the basic prefill path, then the *real* trigger is
   "chunked dynamic prefill + (some weight-decompression structure)," and
   supported configs may also fail under longer `MAX_PROMPT_LEN`. We have
   not yet tested that — happy to run if useful.
3. **INT8 access violation during decode.** Cell I's `0xC0000005` crash
   inside the first `generate()` happens after a clean construct, with no
   Python traceback. Is this expected (INT8 weight-only NPU LLM not yet
   supported end-to-end), or should it be tracked as a separate issue?
4. **Why per-group + asym specifically?** If Open Question 2 doesn't
   hold and the trigger really is the weight scheme: is there a known
   canonicalization in NPUW that names ZP/scale subgraphs in a way that
   collides 40 times for a 28-layer model with 4 attention sub-projections?
5. **Stateful escape hatch.** Is there a recommended user-side workaround
   for stateful LLM IRs that NPUW can't partition (e.g., an `optimum-cli`
   flag to expose KV-cache as explicit inputs so `Model.reshape` reaches
   them), or is fixing NPUW the only path? `--disable-stateful` is not
   viable — `LLMPipeline` requires a stateful model with `beam_idx`.
6. **Cleaner rejection at the boundary.** Per Intel's own docs, per-group
   asym INT4 is not in the documented NPU LLM matrix. Would Intel consider
   having `optimum-cli` warn (or NPUW reject early) when a non-recommended
   configuration is targeted at NPU, instead of failing deep in the MLIR
   partitioner? That would prevent users (us, Diego, the original reporter)
   from spending cycles triaging an unsupported config.

Happy to share the IRs, the export venv lockfile, the verbose log dumps, the
end-to-end generate logs, or run additional cells (e.g., per-group + sym +
`MAX_PROMPT_LEN: 2048` to test Open Question 2) if any of those would help
triangulate.

---

## Status of this draft

**NOT YET POSTED.** Awaiting Lead Architect approval. v3.4 corrects two
material flaws found while auditing v3.3:

- [x] End-to-end `pipe.generate()` now run on every "OK" NPUW cell (B-sym, H, I)
- [x] INT8 (cell I) demoted from "OK NPU verified" to "construct OK / decode CRASH 0xC0000005"
- [x] Acknowledgment that per-group asym is outside Intel's documented NPU LLM recipe
- [x] Open Question 2 added (chunked-prefill submodel as the possibly-real trigger)
- [x] Open Question 3 added (INT8 access violation, possibly separate issue)
- [x] Open Question 6 added (cleaner rejection of non-recommended configs)

No GitHub posting will happen without your explicit go-ahead.
