# Issue #34450 — Reproduction Update (OV 2026.0.0)

> **Draft v3.2.** Supersedes v3.1.
> **What changed vs v3.1:** v3.1 mislabeled the failing case as "per-group INT4 **sym**". The
> nncf bitwidth-distribution logs (cell_b_export.log line 22, cell_h_export.log line 22) prove
> that **both** the failing case (cell B/G) and the succeeding case (cell H/G-H) use
> `int4_asym`. The actual differentiator is **`--group-size 128` (per-group) vs `--group-size -1`
> (channel-wise)**, not symmetry. Symmetric INT4 (`--sym`) was never exercised in this matrix
> — it is queued as a follow-up. Also adds a reconciliation against the issue title's
> `as_convolution` LLVM ABORT signature, an honest split between the two distinct failure
> modes observed (NPUW partitioner vs raw NPU plugin), and a fuller environment fingerprint
> against Intel's documented OV 2026.1 NPU LLM stack requirements.

## tl;dr

- On OpenVINO **2026.0.0**, the original SIGABRT now surfaces as a structured Python
  `RuntimeError` with a clean stack into `npuw/compiled_model.cpp:516`. NPUW failure
  signature: **`StopLocationVerifierPass: Found 40 duplicated names after full verification`**.
  Reproducible without the speculative-decoding wrapper — plain
  `LLMPipeline(ir, "NPU")` is sufficient.
- The IR is structurally valid: same artifact compiles fine on CPU (1.6 s) and GPU
  (6.9 s). The failure is in NPUW's partitioning / sub-graph compile path.
- **NPUW partition matrix (4-cell):** the StopLocationVerifierPass duplicate-name failure
  is observed on **per-group INT4 asym (`--group-size 128`)**. The same IR family
  compiles through NPUW when re-exported as **channel-wise INT4 asym (`--group-size -1`,
  19.30 s)** or **INT8 (16.45 s)**. The fourth cell (per-group INT4 asym + `--disable-stateful`)
  is excluded — see "honest cell-C disposition" below.
- **Symmetric INT4 (`--sym`) is not yet tested.** Per Intel's own
  [OV 2026.1 NPU LLM guide](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html),
  `--sym` is part of the *officially recommended* export recipe for NPU LLMs. We should
  run it before claiming a complete trigger characterization. Queued.
- **Direct NPU compile (no NPUW)** of the same IR family — and of the channel-wise INT4
  and INT8 IRs — fails with a different signature: `to_shape was called on a dynamic
  shape` originating at `__module.model.layers.0.input_layernorm/aten::mul/Multiply`.
  This is the documented NPU plugin static-shape limitation; it is *not* the NPUW bug
  in this issue. Surfaced separately so the two failure modes are not conflated.
- The documented "reshape to static shapes" workaround does **not** apply to optimum-intel
  stateful LLM IRs — `model.reshape({...})` constrains only the four visible inputs;
  KV-cache lives in 56 internal `ReadValue`/`Assign` Variables that `reshape()` does not
  reach. (Cell K probe — full result attached.)

## Reconciliation with the issue title

The original issue title cites **`LLVM ABORT in as_convolution pass — degenerate
0-channel shape`**. Our reproduction on OV 2026.0.0 hits **`StopLocationVerifierPass:
Found 40 duplicated names`** instead — a different MLIR pass and a different diagnostic.
We do **not** observe `as_convolution` or any 0-channel shape diagnostic on this stack.

Plausible explanations (we have not bisected which is correct):

1. The 2026.0.0 NPU compiler reorders or short-circuits the pass pipeline relative to
   whatever release the original report ran on, and the duplicate-name verification
   trips before `as_convolution` is reached.
2. Both diagnostics are downstream of the same root cause (NPUW partitioner producing
   a sub-graph with malformed naming and degenerate shapes), and which one fires depends
   on driver / compiler version.
3. They are distinct bugs with overlapping triggers.

If the OpenVINO team can confirm whether (1), (2), or (3) is correct, we can refile or
narrow accordingly. We do not want to claim this reproduction *is* #34450 if it is in
fact a related-but-distinct issue.

## Environment

| | Compile-time `.venv` (issue stack) | Export-time `.export-venv` | Intel's documented stack for OV 2026.1 NPU |
|---|---|---|---|
| openvino | `2026.0.0` | `2026.0.0` | `2026.1` |
| openvino-genai | `2026.0.0.0` | — | `2026.1` |
| optimum-intel | `1.27.0.dev0+d8864c45` (editable) | `1.27.0` | `1.25.2` |
| optimum | `2.1.0.dev0` | `2.1.0` | (n/a) |
| transformers | `5.3.0` | `4.51.3` | `4.51.3` (strongly recommended) |
| nncf | `3.0.0` | `3.0.0` | `2.18.0` |
| torch | `2.10.0` | `2.6.0+cpu` | (n/a) |

Host: Windows 11 Pro 26100, Intel Core Ultra 7 258V (Lunar Lake), Arc 140V GPU,
AI Boost NPU driver `32.0.100.4724` (2026-03-18). Intel's troubleshooting guidance
recommends NPU driver `32.0.100.3104` or newer; we are well above that.

**Stack divergences from Intel's documented baseline** (none of these is necessarily
the bug, but flagging them for completeness):

- We are on OV 2026.0.0; Intel's NPU GenAI guide is for 2026.1. 2026.1 makes
  Compiler-In-Plugin (CiP) the default; 2026.0 still uses the driver compiler by
  default. Cell J2 (`NPU_COMPILER_TYPE=DRIVER` explicit) reproduces the
  raw-NPU dynamic-shape failure but does not reach NPUW.
- Runtime venv ships `transformers==5.3.0`. The export venv pins `4.51.3`
  (matching Intel's recommendation), so the on-disk IR is built on the documented
  stack. The runtime mismatch could matter for tokenizer behavior but should not
  affect the C++ NPUW partitioner pass.
- nncf 3.0.0 vs documented 2.18.0 — newer.

## NPUW partition matrix (the core finding)

All four cells use the same `repro_compile.py --mode llmpipeline --device NPU`
harness. nncf-reported weight scheme is taken verbatim from each cell's
`<cell>_export.log`.

| Cell | Export args | nncf-reported scheme | NPUW outcome | Compile time |
|---|---|---|---|---|
| G   | `--weight-format int4 --group-size 128 --ratio 1.0`             | `int4_asym, group size 128` | **FAIL** — `StopLocationVerifierPass: 40 duplicated names` | \~6 s to fail |
| G-H | `--weight-format int4 --group-size -1`                          | `int4_asym, per-channel`    | **OK** | 19.30 s |
| G-I | `--weight-format int8`                                          | (INT8 weight-only)           | **OK** | 16.45 s |
| G-C | `--weight-format int4 --group-size 128 --ratio 1.0 --disable-stateful` | `int4_asym, group size 128` (stateless) | **N/A** — fails before NPUW: `Stateful models without 'beam_idx' input are not supported in StatefulToStateless transformation`. `--disable-stateful` is incompatible with `LLMPipeline`. |

So the NPUW partitioner is producing a name collision specifically for the per-group
INT4 graph topology, not for INT8 or for channel-wise INT4. That should narrow the
search for the duplicated-name source significantly.

**Honest scope statement.** This matrix establishes that **per-group INT4 asym is
sufficient** to trigger the NPUW failure on this Qwen3-0.6B IR. It does **not**
establish that asymmetry is *necessary* — symmetric INT4 (`--sym`) has not yet been
exercised through NPUW. Per Intel's NPU LLM guide, `--sym` is part of the recommended
export recipe, so the next test we run will be a fresh export with
`--weight-format int4 --group-size 128 --ratio 1.0 --sym` and the same NPUW harness.
We will append the result here before posting.

## Failure stack (cell G — the canonical NPUW failure)

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

Reproduction is independent of the speculative-decoding wrapper. Plain
`LLMPipeline(ir, "NPU")` is sufficient.

## Direct NPU plugin failure (separate, not the NPUW bug)

For completeness and to avoid the OpenVINO team chasing the wrong signature: cells
F, H, I, J2 all attempt to compile their respective IRs directly with
`Core().compile_model(ir, "NPU")` (no NPUW). All four fail the same way at
`__module.model.layers.0.input_layernorm/aten::mul/Multiply`:

```
[ERROR] [vpux-compiler] Got Diagnostic at loc(fused<{name = ".../Multiply", type = "Multiply"}>) :
  Got non broadcastable dimensions pair :
  '9223372036854775807' and -9223372036854775808'
RuntimeError: ... [NPU_VCL] Compiler returned msg:
  to_shape was called on a dynamic shape.
```

This is the documented NPU plugin "static shapes only" limitation hitting the
optimum-intel stateful IR's `?,?,1024` activation shape. It is **not** the NPUW
duplicate-name bug. Including it here so it isn't conflated; happy to remove if
not useful.

## What else the matrix rules in/out

| Hypothesis | Verdict | Evidence |
|---|---|---|
| IR is malformed | Ruled out | Cells D/E: same IR (cell_b) compiles on CPU (1.6 s) and GPU (6.9 s). |
| Failure requires the spec-decode `LLMPipeline(target, "GPU", draft_model=…)` wrapper | Ruled out | Cell G uses plain `LLMPipeline(ir, "NPU")` and reproduces. |
| Reshaping to static shapes (documented NPU workaround) lets the model compile | Ruled out **for stateful IRs** | Cell K: `model.reshape({input_ids:[1,1024], attention_mask:[1,1024], position_ids:[1,1024], beam_idx:[1]})` succeeds — output partial shape becomes `[1,1024,151936]` — but all 56 KV-cache `ReadValue`/`Assign` Variables remain `[?,8,?,128]`. `core.compile_model(model, "NPU")` then still fails with `to_shape was called on a dynamic shape`. The dynamic dims are in the stateful Variables that `Model.reshape({...})` does not address. |
| `NPU_COMPILER_TYPE=MLIR` is a valid escape hatch | Ruled out | Cell J1: rejected as `Value 'MLIR' is not a valid COMPILER_TYPE option` on OV 2026.0.0. Only `DRIVER` and `PLUGIN` are accepted. |
| `NPU_COMPILER_TYPE=DRIVER` changes the direct-compile failure | Ruled out | Cell J2: same dynamic-shape error as cell F. |
| Per-group INT4 **sym** also fails | **Untested** | Queued — fresh export with `--sym`, same NPUW harness. |

## Reproduction

```bash
# .export-venv: optimum-intel 1.27.0, optimum 2.1.0, transformers 4.51.3, nncf 3.0.0
optimum-cli export openvino \
  --model Qwen/Qwen3-0.6B \
  --task text-generation-with-past \
  --weight-format int4 --group-size 128 --ratio 1.0 \
  ./qwen3-0.6b-int4-asym-g128

# .venv: openvino 2026.0.0, openvino-genai 2026.0.0.0
python -c "
from openvino_genai import LLMPipeline
LLMPipeline('./qwen3-0.6b-int4-asym-g128', 'NPU')
"
```

Swapping `--group-size 128` for `--group-size -1` (channel-wise INT4) or
`--weight-format int8` makes the same code path compile cleanly through NPUW.

## Artifacts

| Cell | Description | IR `xml` sha256 (prefix) | NPUW outcome |
|---|---|---|---|
| B / G   | per-group INT4 asym (the failing case)              | `467f67b16f9806b0…` | FAIL — `StopLocationVerifierPass` |
| C / G-C | per-group INT4 asym + `--disable-stateful`          | `3b0dd0bb85608d77…` | N/A — incompatible with LLMPipeline |
| H / G-H | channel-wise INT4 asym                              | `0628da3f9f23c35b…` | OK (19.30 s) |
| I / G-I | INT8                                                | `6e662ae7ed0e8554…` | OK (16.45 s) |
| (queued) | per-group INT4 **sym** (`--sym`)                   | (pending)           | (pending) |

Per-cell logs, full JSON matrix (`compile_matrix.json`), and the Cell K reshape probe
results can be uploaded if useful.

## Caveats and unresolved questions for the OpenVINO team

1. **Reconciliation with the issue title.** Are `StopLocationVerifierPass: 40 duplicated
   names` (what we observe on 2026.0.0) and `LLVM ABORT in as_convolution pass —
   degenerate 0-channel shape` (the issue title) the same root cause, or distinct bugs
   with overlapping triggers? We don't want to misfile.
2. **NPU vs fallback verification.** Cells G-H and G-I report `OK` from
   `LLMPipeline(ir, "NPU")` but our harness does not currently query
   `compiled_model.get_property("EXECUTION_DEVICES")`. We would like to verify those
   were genuine NPU compiles (not silent CPU/GPU fallback) before claiming the bug is
   per-group-specific. Happy to extend the harness if the team wants that confirmation.
3. **Per-group INT4 sym.** Per Intel's NPU LLM guide, `--sym` is part of the
   recommended export recipe. We will append the result of the symmetric-INT4 cell here
   before posting; the post-content claim today is only that **per-group INT4 asym is
   sufficient** to trigger the failure.
4. **Stateful escape hatch.** For stateful LLM IRs that NPUW currently fails to
   partition, is there a recommended user-side workaround (e.g., an `optimum-cli` flag
   to expose KV-cache as explicit inputs so `model.reshape()` can fully static-ize the
   graph), or is fixing NPUW the only path? `--disable-stateful` is not viable —
   `LLMPipeline` requires a stateful model with `beam_idx`.
5. **Stack divergence.** Our runtime is on OV 2026.0.0 + transformers 5.3.0 +
   nncf 3.0.0 vs Intel's documented OV 2026.1 + transformers 4.51.3 + nncf 2.18.0.
   The IR was built with the documented export stack, so the NPUW bug observed here
   is in the C++ partitioner / compiler — not the Python tokenizer or transformers
   tracer. Worth re-running on a clean 2026.1 stack to confirm.

## Status of this draft

**NOT YET POSTED.** Pending: (a) Lead Architect approval, (b) the queued symmetric-INT4
cell result, (c) optionally an `EXECUTION_DEVICES` query patch to repro_compile.py.
