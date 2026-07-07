# Issue #34450 — v3.6 Draft (POST-READY)

**Status:** NOT YET POSTED. Awaiting Lead Architect approval.
**Target:** https://github.com/openvinotoolkit/openvino/issues/34450
**Reply to:** @diego-villalobos
**Supersedes:** v3.5 (kept on disk as historical reference)

Changes from v3.5: stripped internal draft-history headers and the "Status
of this draft" footer; trimmed the env table (removed `torch` rows that
aren't load-bearing for an NPU compile bug); added an inline `LOCALAPPDATA`
cache-check one-liner so Intel can replicate the cold-compile claim;
referenced the harness (`repro_compile.py`) and the export driver
(`export_variants.py`) by name in the Artifacts list with offers to share
both venvs' `pip freeze`; demoted the `NPU_COMPILER_TYPE` cells (J1/J2) and
the `Model.reshape` cell (K) to a single "Also tested, available on
request" line so the body stays focused on what triggers and refutes the
StopLocationVerifierPass failure.

---

## Posting instructions

1. Open https://github.com/openvinotoolkit/openvino/issues/34450 in a browser, signed in as the BlarAI GitHub account.
2. Scroll to the bottom of the issue. In the **Add a comment** box, click the **Write** tab (not **Preview**).
3. Copy the **entire** contents of the fenced block below — everything **between** the two `~~~` (tilde-tilde-tilde) lines, but **not** the `~~~` lines themselves — and paste it into the comment box. The outer fence is intentionally `~~~` rather than triple-backticks so the inner ` ``` ` code blocks (PowerShell, bash, plaintext) survive the copy and render correctly on GitHub.
4. Click **Preview** and visually confirm: tables render, code blocks render, the `@diego-villalobos` mention is highlighted as a user link, and there are no stray `~~~` lines left in the comment body.
5. Click **Comment**.
6. After posting, paste the resulting comment URL into chat so it can be archived in `phase2_gates/evidence/issue34450/`.

Do **not** edit the comment after posting unless instructed — GitHub edit history is visible to the Intel team and we want a single clean revision.

---

## Comment body (copy everything between the `~~~` fences)

~~~markdown
@diego-villalobos — thanks for the careful repro on 2026.0.0 and 2026.1.0. We hit the same `StopLocationVerifierPass: Found 40 duplicated names` on `Model0_kv1152_FCEW000__0` and ran a 5-cell NPUW partition matrix plus targeted hypothesis tests to narrow what triggers it. Posting the consolidated findings here in case any of it is useful to the team.

## tl;dr

- **Reproduces your exact failure** on OV 2026.0.0 with `optimum-cli export openvino --task text-generation-with-past --weight-format int4 --group-size 128 --ratio 1.0` followed by `LLMPipeline(ir, "NPU")`. No `as_convolution` / 0-channel diagnostic surfaces — the duplicate-name verifier fails first.
- **The IR is structurally valid:** the same artifact compiles cleanly on CPU (1.6 s) and GPU (6.9 s). Failure is in NPUW's partitioning / sub-graph compile path.
- **Trigger is the per-group asym INT4 weight scheme**, not the chunked dynamic-prefill code path. Confirmed by forcing `MAX_PROMPT_LEN=1023` at runtime on the failing config — same submodel `Model0_kv1152_FCEW000__0`, same failure (the static KV shape is baked into the IR at export time, not chosen at compile time).
- **5-cell NPUW partition matrix**, end-to-end `generate()` verified for every "OK" cell:

  | Cell | Export args (delta) | nncf scheme | Construct | `generate(16 tok)` |
  |---|---|---|---|---|
  | G | `--group-size 128` | int4_asym, gs=128 | **FAIL** — StopLocationVerifierPass | n/a |
  | G-B-sym | `--group-size 128 --sym` | **int4_sym**, gs=128 | OK 8.58 s | OK 0.97 s, 16 tok ✓ |
  | G-H | `--group-size -1` | int4_asym, per-channel | OK 8.38 s | OK 2.80 s, 16 tok ✓ |
  | G-I | `--weight-format int8` | INT8 weight-only | OK 8.52 s | NPU: CRASH `0xC0000005`<br>GPU: OK 0.33 s, 16 tok ✓ |
  | G-C | `--group-size 128 --disable-stateful` | (stateless variant) | N/A — fails earlier in StatefulToStateless transformation; `--disable-stateful` is incompatible with `LLMPipeline` | n/a |

  Per-group sym matches Intel's [documented NPU LLM recipe](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html); channel-wise asym is undocumented but happens to work end-to-end. INT8 is now isolated to an **NPU runtime issue** — the IR runs cleanly on GPU.

## Relationship to Intel's documented NPU LLM recipe

The official OV 2026 NPU GenAI page states:

> *LLMs must be exported with the following settings: Symmetric weights compression: `--sym`; 4-bit weight format (INT4 or NF4); Channel-wise or group-wise weight quantization: `--group-size -1` or `--group-size 128`; Maximize the 4-bit weight ratio: `--ratio 1.0`.*

Both the original report and the reproduction command in this thread omit `--sym`. That combination is outside the documented matrix. If the intent is to *reject* per-group asym with a clean configuration error rather than fail in `StopLocationVerifierPass` deep in the partitioner, that would be a strictly better user experience than the current opaque failure.

## Reconciliation with the issue title

Issue title cites `LLVM ABORT in as_convolution pass — degenerate 0-channel shape`. Both we and @diego-villalobos see `StopLocationVerifierPass: Found 40 duplicated names` instead — different MLIR pass, different diagnostic, no `as_convolution` and no 0-channel tensor diagnostic on OV 2026.0.0 or 2026.1.0.

We don't claim to know whether (a) the pass pipeline reordered between the original report's compiler version and 2026.0.0 such that duplicate-name verification trips first, (b) both diagnostics share a root cause in NPUW partitioning, or (c) they're distinct bugs with overlapping triggers. If the team can confirm, we'll narrow or refile accordingly.

## Environment

|  | Compile-time `.venv` (issue stack) | Export-time `.export-venv` |
|---|---|---|
| openvino | `2026.0.0` | `2026.0.0` |
| openvino-genai | `2026.0.0.0` | — |
| optimum-intel | `1.27.0.dev0+d8864c45` (editable) | `1.27.0` |
| optimum | `2.1.0.dev0` | `2.1.0` |
| transformers | `5.3.0` | `4.51.3` (matches Intel's recommended pin) |
| nncf | `3.0.0` | `3.0.0` |

Host: Windows 11 Pro 26100, Intel Core Ultra 7 258V (Lunar Lake), Arc 140V GPU, AI Boost NPU driver `32.0.100.4724` (2026-03-18). Cold-compile runs verified — every Stateful LLM model log line shows `LOADED_FROM_CACHE: NO`, and we confirmed no OV cache directory exists adjacent to the IRs:

```powershell
$cache = "$env:LOCALAPPDATA\openvino_cache"
if (Test-Path $cache) { Get-ChildItem $cache | Measure-Object Length -Sum } else { "no cache dir present" }
```

Full `pip freeze` for both venvs is available on request.

## Failure stack (cell G — identical to @diego-villalobos's report)

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

Reproduction is independent of any speculative-decoding wrapper — plain `LLMPipeline(ir, "NPU")` is sufficient. Same submodel name (`Model0_kv1152_FCEW000__0`) that you report.

The submodel name is informative: `kv1152` matches `MAX_PROMPT_LEN` (1024 default) + `MIN_RESPONSE_LEN` (128 default) = 1152, which is the dynamic chunked-prefill submodel introduced for NPUW LLMs in OV 2025.3+ (`PREFILL_HINT: DYNAMIC` is the default). However, runtime `MAX_PROMPT_LEN` does **not** shift this submodel name — see the chunked-prefill isolation test below.

## NPU-vs-fallback verification (end-to-end)

For each OK cell we ran the harness with `OPENVINO_LOG_LEVEL=3` to confirm the LLM submodel landed on NPU, then called `pipe.generate(...)` to exercise the decode path. Cell B-sym excerpt:

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

Cell H end-to-end: `GENERATE_OK tokens=16 elapsed=2.80s output="<think> | Okay, let's see. The user is asking about the capital of"`.

Cell I constructs but exits `-1073741819` (Windows `STATUS_ACCESS_VIOLATION` `0xC0000005`) during the first `generate()` call on NPU. **Same IR on GPU runs cleanly**: `GENERATE_OK tokens=16 elapsed=0.33s output='<think> | Okay, the user is asking about the capital of France. Let me'`.

So OK cells G-B-sym and G-H genuinely exercise NPU end-to-end. OK cell G-I covers construct only on NPU and is better treated as a **separate decode-time NPU runtime failure** — the IR itself is sound (GPU proves it).

The OV Tokenizer and OV Detokenizer submodels run on CPU (`EXECUTION_DEVICES: CPU`); that is the normal OpenVINO GenAI split, not silent fallback.

## Hypothesis tests

### Q1 — Is the trigger really "per-group + asym," or chunked dynamic prefill?

The failing submodel `Model0_kv1152_FCEW000__0` matches the OV 2025.3+ chunked dynamic-prefill submodel naming pattern. The OK cells (B-sym, H) never expose this submodel in their verbose construct logs — they only show `Model0_prefill`. So a plausible alternative hypothesis was that the *real* trigger is the chunked-prefill code path that per-group + asym happens to activate, not the weight scheme itself.

**Test:** re-export-free runtime override. Compile cell B (the failing per-group asym IR) with `LLMPipeline(ir, "NPU", {MAX_PROMPT_LEN: 1023, MIN_RESPONSE_LEN: 128})`. Naive total KV = 1023 + 128 = 1151, which would not match the chunked `kv1152` submodel name if runtime `MAX_PROMPT_LEN` actually re-shaped the partition.

**Result:** identical failure at the same submodel `Model0_kv1152_FCEW000__0` with the same `StopLocationVerifierPass: Found 40 duplicated names`. The static KV size is baked into the IR at export time; runtime `MAX_PROMPT_LEN` does not change which submodels NPUW produces.

**Conclusion:** the chunked-prefill hypothesis is **refuted**. The trigger is the per-group asym INT4 weight scheme. The submodel name shape just happens to match the chunked-prefill template.

### Q2 — Is the INT8 access violation NPU-specific or a corrupt IR?

**Test:** run the same Cell I INT8 IR on GPU instead of NPU.

**Result:** `GENERATE_OK tokens=16 elapsed=0.33s output='<think> | Okay, the user is asking about the capital of France. Let me'`.

**Conclusion:** the IR is sound. The `0xC0000005` access violation during NPU `generate()` is an NPU runtime bug, distinct from the compile-time duplicate-name failure that is this issue. We can refile separately if the team confirms it's out of scope here.

### Side observation — non-default `MAX_PROMPT_LEN` on the working sym config

While running the Q1 setup we also discovered that Cell B-sym (the *working* sym INT4 config that generates cleanly with defaults) **constructs OK on NPU but crashes with `0xC0000005` during `generate()`** when given `MAX_PROMPT_LEN=2048, MIN_RESPONSE_LEN=128` at construct time. Defaults for the same IR generate 16 tokens cleanly. We're not claiming a root cause — just flagging that NPUW runtime `ov_config` interpretation for non-default prefill/response budgets appears fragile on sym INT4 too.

## Direct NPU plugin failure (separate, not the NPUW bug — relevant to #34617)

To make sure we don't conflate the NPUW partition bug with the NPU plugin dynamic-shape limitation, we also ran direct `Core().compile_model(ir, "NPU")` (no NPUW) against every cell. All five (asym per-group, sym per-group, channel-wise, INT8, even cell B-sym) fail with the *same* signature at `__module.model.layers.0.input_layernorm/aten::mul/Multiply`:

```
[ERROR] [vpux-compiler] Got Diagnostic at loc(fused<{name = ".../Multiply", type = "Multiply"}>) :
  Got non broadcastable dimensions pair :
  '9223372036854775807' and -9223372036854775808'
RuntimeError: ...
  Exception from src\core\src\partial_shape.cpp:266:
  to_shape was called on a dynamic shape.
```

This is **scheme-independent** — the dynamic-shape failure happens regardless of weight format. That matches @YuChern-Intel's earlier observation that "the OpenVINO NPU plugin does not natively support dynamic shapes during inference." Logged here only so the two failure modes don't get confused; this is #34617 territory, not this issue.

## What the matrix rules in/out

| Hypothesis | Verdict | Evidence |
|---|---|---|
| IR is malformed | Ruled out | Same IR (cell B) compiles on CPU (1.6 s) and GPU (6.9 s). |
| Failure requires a spec-decode `LLMPipeline(target, "GPU", draft_model=…)` wrapper | Ruled out | Cell G uses plain `LLMPipeline(ir, "NPU")` and reproduces. |
| Failure requires asym (any weight layout) | Ruled out | Cell H: asym + channel-wise constructs and generates 16 tokens on NPU. |
| Failure requires per-group (any sym setting) | Ruled out | Cell B-sym: sym + per-group constructs and generates 16 tokens on NPU. |
| Failure is silent CPU/GPU fallback masking NPU compile | Ruled out | `OPENVINO_LOG_LEVEL=3` + end-to-end `generate()` on cells B-sym and H confirm NPU. |
| Trigger is the chunked dynamic-prefill code path (not the weight scheme) | Ruled out | Cell B with runtime `MAX_PROMPT_LEN=1023` still fails at the same `Model0_kv1152_FCEW000__0` — static KV shape is baked into the IR at export time. |
| INT8 weight-only IR is corrupt / mis-exported | Ruled out | Cell I on GPU: `GENERATE_OK tokens=16 elapsed=0.33s` with sensible output. The `0xC0000005` is NPU-runtime-specific. |
| INT8 weight-only is a clean alternative on NPU | Not supported by our data | Cell I on NPU: constructs OK, `generate()` crashes with `0xC0000005`. NPU-runtime bug, IR is sound. |

## Reproduction (minimal)

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

To make the failure go away **and** match Intel's documented NPU LLM recipe, add `--sym`:

```bash
optimum-cli export openvino \
  --model Qwen/Qwen3-0.6B \
  --task text-generation-with-past \
  --weight-format int4 --group-size 128 --ratio 1.0 --sym \
  ./qwen3-0.6b-int4-sym-g128
```

`LLMPipeline(ir, "NPU")` then compiles in ~8.5 s on real NPU and generates end-to-end (`pipe.generate("The capital of France is", max_new_tokens=16)` returns sensible Qwen3 output in ~1 s). Channel-wise asym (`--group-size -1`) also works end-to-end on NPU even though it's not in the documented recipe.

## Artifacts

| Cell | Description | Construct | End-to-end `generate(16)` |
|---|---|---|---|
| B / G | per-group INT4 **asym** | FAIL — StopLocationVerifierPass | n/a |
| B-sym / G-B-sym | per-group INT4 sym (default `MAX_PROMPT_LEN`) | OK 8.58 s | NPU OK 0.97 s, sensible output |
| B-sym + `MAX_PROMPT_LEN=2048` | per-group INT4 sym, larger prefill budget | OK on NPU | CRASH `0xC0000005` during generate (side observation) |
| B + `MAX_PROMPT_LEN=1023` | per-group INT4 asym, smaller prefill budget | FAIL — same `Model0_kv1152` submodel | n/a — Q1 refutation evidence |
| H / G-H | channel-wise INT4 asym | OK 8.38 s | NPU OK 2.80 s, sensible output |
| I / G-I | INT8 weight-only | OK 8.52 s | NPU CRASH `0xC0000005`, GPU OK 0.33 s, sensible output |
| C / G-C | per-group INT4 asym + `--disable-stateful` | N/A — fails before NPUW | n/a |

The whole matrix is driven by two scripts: `export_variants.py` (one IR per cell, deterministic, runs in the export venv) and `repro_compile.py` (a subprocess-isolated harness that compiles and optionally calls `generate()`, runs in the runtime venv). Per-cell logs (`cell_<id>_export.log`, `cell_<id>_npuw[_logged].log`, `cell_<id>_direct.log`, `cell_<id>_e2e.log`, `cell_b_short1023.log`, `cell_b_sym_chunked2048.log`, `cell_i_gpu.log`), the consolidated JSON matrix (`compile_matrix.json`), the `OPENVINO_LOG_LEVEL=3` device-attribution dumps, both venvs' `pip freeze`, and the two scripts above are all available on request — happy to attach to this issue if it's easier than a follow-up exchange.

Also tested and not surfaced here in detail because the results don't change anything for this issue: `NPU_COMPILER_TYPE=MLIR` (rejected as `Value 'MLIR' is not a valid COMPILER_TYPE option` on OV 2026.0.0 — only `DRIVER` and `PLUGIN` are accepted) and `NPU_COMPILER_TYPE=DRIVER` (same `to_shape was called on a dynamic shape` as the default direct-NPU path); also `Model.reshape({input_ids, attention_mask, position_ids, beam_idx})` on the optimum-intel stateful IR (constrains only the four visible inputs — the 56 internal KV-cache `ReadValue`/`Assign` Variables stay `[?,8,?,128]`, so the direct-NPU compile still fails at the same Multiply node).

## Open questions

1. **Same root cause as the issue title?** Are `StopLocationVerifierPass: 40 duplicated names` (what we and @diego-villalobos both observe on 2026.0.0 / 2026.1.0) and `LLVM ABORT in as_convolution pass — degenerate 0-channel shape` (the title) the same root cause? If yes, this issue covers both. If no, we should refile the duplicate-name failure separately.
2. **Why per-group + asym specifically?** Is there a known canonicalization in NPUW that names ZP/scale subgraphs in a way that collides 40 times for a 28-layer model with 4 attention sub-projections? (Per-channel asym, by contrast, doesn't trip the verifier — channel-wise has no per-group ZP tensor naming, which is consistent with a 40 ≈ 28 × ~1.4 collision count.)
3. **Stateful escape hatch.** Is there a recommended user-side workaround for stateful LLM IRs that NPUW can't partition (e.g., an `optimum-cli` flag to expose KV-cache as explicit inputs so `Model.reshape` reaches them), or is fixing NPUW the only path? `--disable-stateful` is not viable — `LLMPipeline` requires a stateful model with `beam_idx`.
4. **Cleaner rejection at the boundary.** Per Intel's own docs, per-group asym INT4 is not in the documented NPU LLM matrix. Would Intel consider having `optimum-cli` warn (or NPUW reject early) when a non-recommended configuration is targeted at NPU, instead of failing deep in the MLIR partitioner? That would prevent users from spending cycles triaging an unsupported config.
5. **Filing the INT8 NPU-runtime crash separately?** Cell I's `0xC0000005` inside the first `generate()` on NPU happens after a clean construct (and the same IR runs end-to-end on GPU, so the IR is sound). If the team agrees this is out of scope for #34450, we'd be glad to file a separate issue with the IR + log.

Happy to share the IRs, both venvs' lockfiles, the verbose log dumps, or run additional cells if any of those would help triangulate.

---

*Per [OpenVINO AI Usage Policy](https://github.com/openvinotoolkit/openvino/blob/master/AI_USAGE_POLICY.md):*

```text
AI assistance used: yes
If yes: AI assistants (GitHub Copilot / Claude) helped design the 5-cell NPUW
  partition matrix, draft the per-cell harness scripts (export_variants.py,
  repro_compile.py), draft this comment, and cross-check the failure-mode
  taxonomy. All hypotheses (Q1 chunked-prefill refutation, Q2 INT8 GPU
  rebuttal) and the matrix design were proposed and reviewed by the human
  reporter before execution.
Human validation performed: every cell was executed locally on the reporter's
  hardware (Intel Core Ultra 7 258V, AI Boost NPU driver 32.0.100.4724,
  OV 2026.0.0); all log excerpts quoted above were verified byte-for-byte
  against the corresponding on-disk log files; all timing numbers, exit
  codes, submodel names, and failure stacks are first-hand observations from
  those runs, not model output. The reporter understands every claim made
  here and can reproduce or extend any cell on request.
```
~~~

---

## Pre-post checklist (for the operator)

- [ ] Verify the GitHub account being used is the intended BlarAI account.
- [ ] Confirm we are commenting on **#34450** (not #34617 — those are separate per the comment body).
- [ ] In the GitHub Preview tab, confirm: tables render, both fenced code blocks render, `@diego-villalobos` and `@YuChern-Intel` render as user mentions, and the **AI Usage Policy disclosure block** at the bottom is present and renders as a code block.
- [ ] After clicking **Comment**, copy the resulting comment URL and archive it.
- [ ] Do not edit the comment after posting.
