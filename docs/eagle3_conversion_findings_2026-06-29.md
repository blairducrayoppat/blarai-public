# EAGLE-3 OpenVINO Conversion — Findings (2026-06-29)

**Context.** Session 1 of the OpenVINO 2026.2 upgrade aimed to *prepare* an EAGLE-3 speculative-decoding draft
(Qwen3-8B, and — per the premise correction below — Qwen3-14B) for a Session-2 A/B against the existing vanilla
Qwen3-0.6B-pruned-6L draft. "Prepare" = convert to OpenVINO IR + smoke-test on the Arc 140V; **not** benchmark.
A prior attempt (2026-03-02, OV GenAI 2026.0.0) was dispositioned **FRAMEWORK_NOT_SUPPORTED**.

**Verdict: BLOCKED (conversion).** The 2026-03 *version-lag* is closed, but a **new, deeper structural
incompatibility** prevents converting the AngelSlim Qwen3 EAGLE-3 checkpoints with optimum-intel v2.0.0.
Recommendation: **defer EAGLE-3** to a focused future effort. Zero hardware time was spent (all failures were
fast CPU-side load errors). This finding is precise enough to file upstream.

---

## What changed since 2026-03 (the version-lag is closed)

The March failure was that the EAGLE-3 architecture classes could not be **loaded at all** by the then-current
optimum-intel (v1.27.0, 2025-12-23) — no exporter was registered, so the export aborted before producing any IR
("state dictionary corrupted" via the dynamic-module fallback). The AngelSlim EAGLE-3 exporter
(**optimum-intel PR #1588**, merged 2026-02-10) only reached PyPI in **optimum-intel v2.0.0 (2026-06-10)**.

With **optimum-intel v2.0.0 + OpenVINO GenAI 2026.2.1**, the exporter IS present and the registered
`LlamaForCausalLMEagle3` class now loads — i.e. we get *past* architecture resolution. The correct invocation is
**without** `--trust-remote-code` (the AngelSlim repos ship no modeling `.py`; the flag wrongly forced
transformers' dynamic-module path → `class_reference.split("--")` `ValueError`), plus `accelerate` installed
(transformers' `init_empty_weights`).

## The new blocker — a parameter-structure + vocab-size mismatch

Once the registered class loads the weights (transformers 5.0.0, the recipe-pinned version, gives the clearest
report), the checkpoint and the model class **disagree on the EAGLE-3 layer structure**:

```
ckpt has (UNEXPECTED to the model):  midlayer.self_attn.{q,k,v,o}_proj.weight, midlayer.mlp.{gate,up,down}_proj.weight,
                                     midlayer.input_layernorm.weight, midlayer.post_attention_layernorm.weight,
                                     midlayer.hidden_norm.weight, fc.weight, t2d, d2t
model expects (MISSING from ckpt):   model.layers.0.*  (same sublayers, standard-Llama names), model.embed_tokens.weight
hard MISMATCH:                       lm_head.weight  — ckpt torch.Size([32000, 4096])  vs  model torch.Size([151936, 4096])
```

Interpretation: optimum-intel's `LlamaForCausalLMEagle3` models the EAGLE-3 head as a standard single Llama layer
(`model.layers.0.*`) with a **full-vocabulary** LM head, whereas the AngelSlim checkpoint uses the EAGLE-3-native
`midlayer.*` naming, the `fc` hidden-state fusion projection, the `t2d`/`d2t` target↔draft vocab maps, and a
**draft-vocabulary (32000)** LM head. The two are not load-compatible. `ignore_mismatched_sizes=True` would "load"
but reinit every mismatched/missing tensor to noise → a broken draft, so it is not a valid workaround.

**Reproduced on:** `AngelSlim/Qwen3-8B_eagle3` (fresh download, 799 MB, intact) AND
`AngelSlim/Qwen3-14B_eagle3` (on-disk, 1,219,459,838 B, intact); transformers **4.51.0** ("state dictionary
corrupted") and **5.0.0** (the explicit mismatch report above). Full report:
`scratchpad/eagle3_mismatch_report.txt`. Toolchain: optimum-intel 2.0.0, optimum 2.2.0, openvino-genai 2026.2.1.0,
nncf 3.2.0, accelerate 1.14.0, torch 2.12.1+cpu — all in a throwaway venv (the runtime `.venv` was never touched).

## Premise correction (carried from the §5 catalog)

The brief stated "no 14B EAGLE-3 draft exists; training one is out of scope, defer." **A trained
`AngelSlim/Qwen3-14B_eagle3` head does exist** (and is on disk) — so no training is needed. But it converts no
better than the 8B (same structural mismatch), so the *practical* outcome is the same: **neither size is
preparable today** via optimum-intel v2.0.0.

## Recommendation + options (for a future focused effort — operator's call)

Defer. Cost/benefit favors it: R5's calibration is that EAGLE-3's gain on a bandwidth-bound iGPU is **modest**
(~1.3–1.8× over no-draft, possibly only marginally above the already-tuned 0.6B draft that gives ~1.5×) — this was
always a speculative A/B, not a sure win. Options, lowest-effort first:
1. **File an optimum-intel issue** with the report above (the operator is an upstream contributor; this is exactly
   the actionable shape — the v2.0.0 `LlamaForCausalLMEagle3` modeling does not match the AngelSlim checkpoint
   layout / draft-vocab `lm_head`). Likely the highest-leverage move.
2. **Wait** for an optimum-intel fix to #1588's modeling, or for a **pre-converted OpenVINO-IR** EAGLE-3 draft to
   be published (none exists today — HF `OpenVINO` org returns zero).
3. **Try a different EAGLE-3 source** whose checkpoint matches optimum-intel's expected naming (uncertain — most
   public Qwen3 EAGLE-3 heads use the same `midlayer`/`fc`/`t2d` convention).
4. **Write a key-remapping shim** (`midlayer.*`→`model.layers.0.*`, handle `fc`/`t2d`/`d2t`, draft-vocab `lm_head`)
   — a real but bounded engineering task; only worth it if the measured iGPU gain proves material.

**Session-2 impact:** EAGLE-3 is **NOT prepared**. The Session-2 brief drops the "EAGLE-3 vs vanilla" matrix row
(or lists it as blocked-pending-upstream). The existing vanilla 0.6B-draft spec-decode is unaffected and remains
the production path.
