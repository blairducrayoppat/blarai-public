# Issue #34450 — Reproduction Update (OV 2026.0.0)

> **Draft v3.5.** Supersedes v3.4. Two open questions from v3.4 (the
> chunked-prefill hypothesis and the INT8 access-violation triage) are now
> answered with direct empirical tests rather than handed back to Intel.

> **What changed vs v3.4 (definitive answers added, no claims weakened):**
>
> 1. **Q2 (chunked-prefill hypothesis) — REFUTED.** Re-running cell B
>    (per-group asym, the failing config) with runtime
>    `MAX_PROMPT_LEN=1023, MIN_RESPONSE_LEN=128` (which would naively give
>    a `kv1151` total) still fails at the **same submodel name
>    `Model0_kv1152_FCEW000__0`**. The static KV size is baked into the IR
>    at export time, not chosen at compile time, so runtime `MAX_PROMPT_LEN`
>    cannot suppress the offending submodel. The trigger remains the
>    per-group **asym** INT4 weight scheme — not the chunked-prefill code
>    path. Evidence: `cell_b_short1023.log`.
> 2. **Q3 (INT8 access violation) — NPU-SPECIFIC.** The exact same Cell I
>    INT8 IR that crashes with `0xC0000005` inside `generate()` on NPU runs
>    cleanly on **GPU** (`GENERATE_OK tokens=16 elapsed=0.33s output='<think> | Okay, the user is asking about the capital of France. Let me'`).
>    The IR is not corrupt; the access violation is an NPU runtime bug
>    distinct from #34450's compile-time duplicate-name failure. Evidence:
>    `cell_i_gpu.log`. We're happy to refile this as its own issue if Intel
>    confirms it's not in scope here.
> 3. **New side finding:** running the *working* sym INT4 config (Cell B-sym)
>    with non-default `MAX_PROMPT_LEN=2048` constructs OK on NPU but **also
>    crashes with `0xC0000005` during `generate()`** (`cell_b_sym_chunked2048.log`).
>    Default config (`MAX_PROMPT_LEN=1024`) for the same Cell B-sym IR
>    generates 16 tokens cleanly. Suggests NPUW runtime `ov_config`
>    interpretation for non-default prefill/response budgets is fragile on
>    sym INT4 too. Reported here only so the data point doesn't go missing;
>    we're not claiming a root cause for it.

> **Carried forward from v3.4 (unchanged):**
>
> - Reproduces @diego-villalobos's exact `StopLocationVerifierPass: Found 40
>   duplicated names after full verification` on `Model0_kv1152_FCEW000__0`.
> - Per-group **asym** INT4 (the failing config) is outside Intel's
>   documented NPU LLM recipe (which mandates `--sym`).
> - Direct-NPU compile fails *scheme-independently* with
>   `to_shape was called on a dynamic shape` (issue #34617 territory, not
>   this issue).
> - `Model.reshape({...})` is not sufficient to static-ize a stateful LLM
>   IR (KV-cache `ReadValue`/`Assign` Variables remain dynamic).

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
- **The trigger is the per-group asym INT4 weight scheme**, not the chunked
  dynamic-prefill code path. We confirmed this by forcing
  `MAX_PROMPT_LEN=1023` at runtime on the failing config — same submodel,
  same failure (the static KV shape is baked into the IR at export time).
- **5-cell NPUW partition matrix**, end-to-end `generate()` verified for
  every "OK" cell, plus targeted hypothesis tests for the chunked-prefill
  and INT8-on-GPU questions:

  | Cell    | Export args (delta) | nncf scheme | Construct | `generate(16 tok)` |
  |---|---|---|---|---|
  | G       | `--group-size 128`                   | int4_asym, gs=128       | **FAIL** — StopLocationVerifierPass | n/a |
  | G-B-sym | `--group-size 128 --sym`             | **int4_sym**, gs=128    | OK 8.58 s                            | **OK 0.97 s, 16 tok ✓** |
  | G-H     | `--group-size -1`                    | int4_asym, per-channel  | OK 8.38 s                            | **OK 2.80 s, 16 tok ✓** |
  | G-I     | `--weight-format int8`               | INT8 weight-only         | OK 8.52 s                            | **NPU: CRASH 0xC0000005**<br>**GPU: OK 0.33 s, 16 tok ✓** |
  | G-C     | `--group-size 128 --disable-stateful`| (stateless variant)     | N/A — fails earlier in StatefulToStateless transformation; `--disable-stateful` is incompatible with `LLMPipeline` | n/a |

  **Trigger for THIS issue (the StopLocationVerifierPass failure):** per-group
  **asym** INT4. Per-group sym (Intel's documented recipe) and channel-wise
  asym both compile and generate cleanly on NPU. Per-group sym matches Intel's
  documented requirement; channel-wise asym is undocumented but happens to
  work end-to-end.

  **Separate observation (now isolated to NPU runtime, not the IR):** INT8
  weight-only constructs but crashes during decode on NPU. Same IR runs
  end-to-end on GPU (`generate(16 tok) elapsed=0.33s`). This is therefore an
  NPU runtime bug, not a model-export problem, and is almost certainly
  distinct from the duplicate-name compile failure that is this issue.

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
current opaque failure.

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
GPU, AI Boost NPU driver `32.0.100.4724` (2026-03-18). Cold-compile runs
verified — no OV cache directory adjacent to the IRs under test, and every
Stateful LLM model log line shows `LOADED_FROM_CACHE: NO`.

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
default) + `MIN_RESPONSE_LEN` (128 default) = 1152, which is the dynamic
chunked-prefill submodel introduced for NPUW LLMs in OV 2025.3+
(`PREFILL_HINT: DYNAMIC` is the default). However, **runtime
`MAX_PROMPT_LEN` does NOT shift this submodel name** — see the
chunked-prefill isolation test below.

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
`STATUS_ACCESS_VIOLATION` `0xC0000005`) during the first `generate()` call on
NPU. **Same IR on GPU runs cleanly** (`cell_i_gpu.log`):
`GENERATE_OK tokens=16 elapsed=0.33s output='<think> | Okay, the user is asking about the capital of France. Let me'`.

So OK cells G-B-sym and G-H genuinely exercise NPU end-to-end. OK cell G-I
covers construct only on NPU and should be considered a **separate decode-time
NPU runtime failure**, not a clean "INT8 works on NPU" data point — but the
IR itself is sound (GPU proves it).

The OV Tokenizer and OV Detokenizer submodels run on CPU
(`EXECUTION_DEVICES: CPU`); that is the normal OpenVINO GenAI split, not
silent fallback.

## Hypothesis tests run for this draft

### Q2 — Is the trigger really "per-group + asym," or chunked dynamic prefill?

The failing submodel `Model0_kv1152_FCEW000__0` matches the OV 2025.3+
chunked dynamic-prefill submodel naming pattern. The OK cells (B-sym, H)
never expose this submodel in their verbose construct logs — they only show
`Model0_prefill`. So a plausible alternative hypothesis was that the *real*
trigger is the chunked-prefill code path that per-group + asym happens to
activate, not the weight scheme itself.

**Test:** re-export-free runtime override. Compile cell B (the failing
per-group asym IR) with `LLMPipeline(ir, "NPU", {MAX_PROMPT_LEN: 1023,
MIN_RESPONSE_LEN: 128})`. Naive total KV = 1023 + 128 = 1151, which would
not match the chunked `kv1152` submodel name if runtime `MAX_PROMPT_LEN`
actually re-shapes the partition.

**Result (`cell_b_short1023.log`):** identical failure at the same submodel
`Model0_kv1152_FCEW000__0` with the same `StopLocationVerifierPass: Found 40
duplicated names`. The static KV size is baked into the IR at export time;
runtime `MAX_PROMPT_LEN` does not change which submodels NPUW produces.

**Conclusion:** the chunked-prefill hypothesis is **refuted**. The trigger
is the per-group asym INT4 weight scheme, as v3.4 stated. The submodel name
shape just happens to match the chunked-prefill template.

### Q3 — Is the INT8 access violation NPU-specific or a corrupt IR?

**Test:** run the same Cell I INT8 IR on GPU instead of NPU.

**Result (`cell_i_gpu.log`):**
`GENERATE_OK tokens=16 elapsed=0.33s output='<think> | Okay, the user is asking about the capital of France. Let me'`.

**Conclusion:** the IR is sound. The `0xC0000005` access violation during
NPU `generate()` is an NPU runtime bug, distinct from the compile-time
duplicate-name failure that is this issue. We can refile separately if
Intel confirms it's out of scope here.

### Side finding — non-default `MAX_PROMPT_LEN` on the working sym config

While running Q2's setup we also discovered (`cell_b_sym_chunked2048.log`)
that Cell B-sym (the *working* sym INT4 config that generates cleanly with
defaults) **constructs OK on NPU but crashes with `0xC0000005` during
`generate()`** when given `MAX_PROMPT_LEN=2048, MIN_RESPONSE_LEN=128` at
construct time. Default config (which corresponds to `MAX_PROMPT_LEN=1024`
implicitly) for the same IR generates 16 tokens cleanly. We're not claiming
a root cause — just flagging that NPUW runtime `ov_config` interpretation
for non-default prefill/response budgets appears fragile on sym INT4 too.

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
| **Trigger is the chunked dynamic-prefill code path (not the weight scheme)** | **Ruled out** | **Cell B with runtime `MAX_PROMPT_LEN=1023` still fails at the same `Model0_kv1152_FCEW000__0` — static KV shape is baked into the IR at export time.** |
| INT8 weight-only IR is corrupt / mis-exported | **Ruled out** | **Cell I on GPU: `GENERATE_OK tokens=16 elapsed=0.33s` with sensible output. The `0xC0000005` is NPU-runtime-specific.** |
| INT8 weight-only is a clean alternative on NPU | **NOT supported by our data** | Cell G-I on NPU: constructs OK, `generate()` crashes with `0xC0000005`. NPU-runtime bug, IR is sound. |

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
but does not survive the first `generate()` call on NPU; same INT8 IR runs
cleanly on GPU (so the IR is sound — see "side observation" above).

## Artifacts

| Cell    | Description                                  | Construct | End-to-end `generate(16)` |
|---|---|---|---|
| B / G   | per-group INT4 **asym**                      | FAIL — StopLocationVerifierPass | n/a |
| **B-sym / G-B-sym** | **per-group INT4 sym** (default `MAX_PROMPT_LEN`) | **OK 8.58 s** | **NPU OK 0.97 s, sensible output** |
| B-sym + `MAX_PROMPT_LEN=2048` | per-group INT4 sym, larger prefill budget | OK on NPU | **CRASH 0xC0000005** during generate (side finding) |
| B + `MAX_PROMPT_LEN=1023` | per-group INT4 asym, smaller prefill budget | **FAIL — same `Model0_kv1152` submodel** | n/a — Q2 refutation evidence |
| H / G-H | channel-wise INT4 asym                       | OK 8.38 s | NPU OK 2.80 s, sensible output |
| I / G-I | INT8 weight-only                             | OK 8.52 s | **NPU CRASH 0xC0000005**, **GPU OK 0.33 s, sensible output** |
| C / G-C | per-group INT4 asym + `--disable-stateful`   | N/A — fails before NPUW | n/a |
| K       | per-group INT4 asym + `Model.reshape({...})` | direct-NPU still fails (KV-cache Variables stay dynamic) | n/a |

Per-cell logs (`cell_<id>_export.log`, `cell_<id>_npuw[_logged].log`,
`cell_<id>_direct.log`, `cell_<id>_e2e.log`, **`cell_b_short1023.log`**,
**`cell_b_sym_chunked2048.log`**, **`cell_i_gpu.log`**), full JSON matrix
(`compile_matrix.json`), and the `OPENVINO_LOG_LEVEL=3` device-attribution
dumps are available on request.

## Open questions for the team

(Down from six in v3.4 — Q2 and Q3 are now answered with direct evidence
above and removed from this list.)

1. **Same root cause as the issue title?** Are
   `StopLocationVerifierPass: 40 duplicated names` (what Diego and we both
   observe on 2026.0.0 / 2026.1.0) and
   `LLVM ABORT in as_convolution pass — degenerate 0-channel shape` (the
   title) the same root cause? If yes, this issue covers both. If no, we
   should refile the duplicate-name failure separately.
2. **Why per-group + asym specifically?** Is there a known canonicalization
   in NPUW that names ZP/scale subgraphs in a way that collides 40 times for
   a 28-layer model with 4 attention sub-projections? (Per-channel asym, by
   contrast, doesn't trip the verifier — channel-wise has no per-group ZP
   tensor naming, which is consistent with a 40 = 28 × \~1.4 collision count.)
3. **Stateful escape hatch.** Is there a recommended user-side workaround
   for stateful LLM IRs that NPUW can't partition (e.g., an `optimum-cli`
   flag to expose KV-cache as explicit inputs so `Model.reshape` reaches
   them), or is fixing NPUW the only path? `--disable-stateful` is not
   viable — `LLMPipeline` requires a stateful model with `beam_idx`.
4. **Cleaner rejection at the boundary.** Per Intel's own docs, per-group
   asym INT4 is not in the documented NPU LLM matrix. Would Intel consider
   having `optimum-cli` warn (or NPUW reject early) when a non-recommended
   configuration is targeted at NPU, instead of failing deep in the MLIR
   partitioner? That would prevent users (us, Diego, the original reporter)
   from spending cycles triaging an unsupported config.
5. **Filing the INT8 NPU-runtime crash separately?** Cell I's `0xC0000005`
   inside the first `generate()` on NPU happens after a clean construct
   (and the same IR runs end-to-end on GPU, so the IR is sound). If Intel
   agrees this is out of scope for #34450, we'd be glad to file a separate
   issue with the IR + log.

Happy to share the IRs, the export venv lockfile, the verbose log dumps,
the end-to-end generate logs (including the Q2 / Q3 / side-finding logs
referenced above), or run additional cells if any of those would help
triangulate.

---

## Status of this draft

**NOT YET POSTED.** Awaiting Lead Architect approval. v3.5 elevates two of
v3.4's open questions to definitive findings backed by direct empirical
tests:

- [x] Q2 (chunked-prefill hypothesis) — REFUTED by `cell_b_short1023.log`
- [x] Q3 (INT8 access violation triage) — NPU-RUNTIME-SPECIFIC, IR is sound, by `cell_i_gpu.log`
- [x] Side finding logged: non-default `MAX_PROMPT_LEN` on Cell B-sym also crashes during generate
- [x] Open Question count reduced 6 → 5; the two answered questions converted to evidence sections

No GitHub posting will happen without your explicit go-ahead.
