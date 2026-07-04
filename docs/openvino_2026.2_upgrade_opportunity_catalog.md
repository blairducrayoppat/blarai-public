# OpenVINO 2026.1.0 → 2026.2.1 — Upgrade-Opportunity Catalog (§5)

**Author:** implementation session (Session 1 of 3), 2026-06-29. **Branch:** `feat/openvino-2026.2-upgrade`.
**Purpose:** the first-class §5 scan the operator asked for — *every* practical improvement the bump (and adjacent
component updates) makes available to BlarAI, presented for the operator to **triage**. The agent implements only
the **do-now** subset he approves; the rest become Session-2 measurements or tracked tickets.

**Method.** Five parallel research agents surveyed, each grounding every claim in primary sources (release notes,
GitHub release tags, PR bodies/diffs via the API, official docs): (R1) OpenVINO **GenAI** changelog 2026.1→2026.2.1;
(R2) OpenVINO **core + GPU plugin + NNCF**; (R3) **optimum-intel + image-gen + model/precision matrix**; (R4) **OVMS
+ serving + security/signing + tooling**; (R5) **EAGLE-3-on-2026.2 feasibility** deep-dive. Where agents disagreed
or web summaries mis-attributed a feature to the wrong version, the version-pinned release-branch source won.

**Filter applied (the operator's only filter — "practical, in-mandate"):** runnable on this hardware (Lunar Lake /
Arc 140V Xe2 iGPU, 31.323 GiB shared) AND consistent with the mandate (pure-GPU, local, air-gapped, fail-closed,
privacy-absolute). Anything violating the mandate is listed as **rejected with the reason**, never silently dropped.

---

## 0. Decisions for you (the triage) — the short list

Everything else is detail. These are the calls only you should make:

| # | Decision | Agent recommendation |
|---|----------|----------------------|
| D1 | **EAGLE-3 (8B + 14B)** — **conversion is BLOCKED** (found during this session; see `eagle3_conversion_findings_2026-06-29.md`). The March *version-lag* is closed (optimum-intel v2.0.0 has the exporter), but a deeper **structural mismatch** between the AngelSlim checkpoints and optimum-intel's `LlamaForCausalLMEagle3` modeling stops the convert for BOTH sizes (intact downloads, both transformers versions). Premise note: a trained 14B draft *does* exist (no training needed) — but it converts no better than the 8B. | **Defer** EAGLE-3; **file the upstream optimum-intel issue** (precise report captured). Drop the EAGLE-3 row from Session 2 (or list blocked-pending-upstream). The vanilla 0.6B-draft spec-decode is unaffected. |
| D2 | **Do-now quality knobs** — add `min_p` (AO answer quality) and `guidance_rescale` (SDXL) as opt-in config knobs, default-off (zero behaviour change until set)? | **Do-now** — trivial, reversible, default-off; measure the quality delta in Session 2. |
| D3 | **INT4 KV-cache quantization on GPU** (the memory lever) — add a config knob now (default = current FP16 behaviour), measure the headroom/quality trade in Session 2? | **Do-now the knob, default-unset**; measure in Session 2. Could let hires-SDXL stop evicting the 14B. |
| D4 | **30B coder accuracy fix** — Intel documents an INT4-MoE-on-GPU long-prompt accuracy defect that hits *exactly* the Qwen3-Coder-30B-A3B; the workaround is one OVMS launch env var (`MOE_USE_MICRO_GEMM_PREFILL=0`, slight TTFT cost). | **Do-now** (OVMS launch config) + measure the accuracy/TTFT delta in Session 2. |
| D5 | **Model swaps to Qwen3.5 / 3.6** — 2026.2 newly enables them on the GPU. They are a **capability/quality decision** (and would *lose* spec-decode — no 3.5/3.6 EAGLE-3 draft exists). | **Escalated, not acted** — keep on the model-upgrade-watch; revisit when an OV INT4 weight + a matched draft both exist. |

The full catalog below is grouped **A: do-now · B: measure-in-Session-2 · C: defer/ticket · D: reject/N-A.**

---

## 1. Premise corrections (evidence-backed — read before the catalog)

- **PC1 — a trained 14B EAGLE-3 draft exists.** Contrary to the brief, `AngelSlim/Qwen3-14B_eagle3`
  (`LlamaForCausalLMEagle3`, 3.09k downloads) is published *and already downloaded* to
  `models/eagle3-qwen3-14b-raw/`. No training project is required. (R3) Decision D1.
- **PC2 — EAGLE-3 version-lag closed, but conversion is STILL blocked one layer deeper (found this session).**
  The March-2026 failure was a version lag — the AngelSlim EAGLE-3 exporter (optimum-intel PR #1588, merged
  2026-02-10) only shipped in **optimum-intel v2.0.0 (2026-06-10)**; March had v1.27.0. With v2.0.0 the exporter IS
  present and the registered `LlamaForCausalLMEagle3` class now loads (no `--trust-remote-code`; the AngelSlim repos
  ship no modeling `.py`). BUT loading the weights then fails on a **structural mismatch** — the AngelSlim
  checkpoint uses `midlayer.*`/`fc`/`t2d`/`d2t` + a draft-vocab (32000) `lm_head`, while optimum-intel's class
  expects `model.layers.0.*`/`model.embed_tokens` + a full-vocab (151936) `lm_head`. Reproduced on 8B + 14B, both
  transformers versions. **EAGLE-3 conversion is therefore BLOCKED today** — see
  `eagle3_conversion_findings_2026-06-29.md`. (R5 + this session's conversion attempt.)
- **PC3 — "non-CB / stateful spec-decode path" is NOT new in 2026.2.** Its source (`speculative_decoding/stateful/`,
  incl. the `num_assistant_tokens` acceptance-rate auto-tune) is byte-identical in 2026.1.0 and 2026.2.1. BlarAI's
  spec-decode behaviour and knobs are unchanged by the bump. The deeper Dynamic-Tree-Search sampler (#3451) and the
  CB EAGLE-3/VLM items merged to `master` *after* the 2026.2 branch cut → a later release, not this one. **Keeping
  the proven Continuous-Batching path through the bump (the original recommendation) stands.** (R1)
- **PC4 — the literal "VLM copy-elimination" the brief named does NOT touch BlarAI's VLM path.** PR #3638 is
  **CB-pipeline-only and Qwen3-VL-specific**, and is host RAM→RAM deep-copy removal (not a CPU↔GPU transfer); its
  own description states the non-CB `pipeline.cpp` is unchanged — and BlarAI runs the **stateful (non-CB)** VLM.
  **The applicable VLM win instead is PR #3640 "slice-before-matmul"** (auto-applied on the *stateful* path: the LM
  head emits logits for the last token only → lower Qwen3-VL-8B TTFT + prefill memory on GPU), plus the GPU-plugin
  Qwen3-VL TTFT/TPOT/load improvement. I verify *these* engage rather than the CB-only one. (R1, R2)

---

## A. DO-NOW candidates (recommend implementing this session, on your approval)

All are trivial/low-effort, low-risk, reversible, and default to current behaviour unless explicitly enabled.

### A1. `min_p` sampling knob for the AO — answer-quality lever *(D2)*
- **What / where:** new `GenerationConfig.min_p` adaptive-truncation sampler, **GenAI 2026.2.0.0** (PR #3752); active
  on the stateful LLMPipeline path the AO uses. Verified absent at 2026.1.0.0, present at 2026.2.1.0.
- **Benefit / measure:** improves AO output quality at `do_sample=true` (PR's own data: BFCL multi-turn tool-calling
  39%→42% on a comparable INT4 model with `min_p=0.05`). Measure on the AO eval set, with/without `min_p∈{0.05,0.1}`.
  No latency cost (a logit filter).
- **Risk:** minimal — **default `0.0` = disabled**, zero behaviour change until set; pure local logit math.
- **Effort:** trivial (one knob in the AO `GenerationConfig` builder + a test).
- **Scope fit:** this session (add the knob, default-off); the A/B measurement is Session 2.

### A2. `guidance_rescale` knob for SDXL — image-quality lever *(D2)*
- **What / where:** `rescale_noise_cfg` (CFG-rescale, Lin et al.) added to image-gen config, **GenAI 2026.2.0.0**
  (PR #3369). Applies to text2image and image2image.
- **Benefit / measure:** mitigates over-saturation/over-exposure at high `guidance_scale` — pairs with the knobs
  `image_gen.py` already exposes (scheduler, guidance_scale, negative_prompt). Set ≈0.7 and A/B in Session 2.
- **Risk:** low — opt-in, default preserves current output; no new egress.
- **Effort:** trivial (expose in `ImageGenConfig` + thread into `gen_kwargs`). *(image-gen is dormant by default — this
  is a latent quality knob ready for go-live, not an active change.)*
- **Scope fit:** this session (add the knob).

### A3. INT4 KV-cache quantization on GPU — the memory lever *(D3)*
- **What / where:** "INT4 KV-cache quantization enabled for GPUs," **core/GPU 2026.2.0** — via `ov::hint::kv_cache_precision`
  (+ `ov::hint::dynamic_quantization_group_size`). Both surfaced via GenAI compile properties. (R2#1, corroborated R4#3.)
- **Benefit / measure:** the single most direct lever on the binding constraint (31.323 GiB shared). KV-cache is the
  term that grows with context and drives co-residency thrash. INT4 vs the FP16 default ≈4× cut on the KV term
  (≈2× vs INT8). Could free enough headroom that the hires-SDXL path stops evicting the 14B. Measure: 16K/32K prompts
  on Qwen3-14B, sweep precision {FP16,INT8,INT4} × peak shared-RAM (In-Use=Total−Available), TTFT, TPOT, quality.
- **Risk:** accuracy regression at INT4 on long contexts (mitigate via group-size). **Caveat:** on XMX/systolic GPUs
  (the Arc 140V has XMX) KV-cache quant is **opt-in** — must be set explicitly; confirm the default with a one-line
  probe before trusting it. Fully reversible (a runtime hint).
- **Effort:** trivial flag (one property in the shared-pipeline GPU config map; no reconversion). Add the knob
  **default-unset** (= today's FP16) so the bump changes nothing until you opt in.
- **Scope fit:** this session (add the knob, default-unset); the sweep is Session 2.

### A4. 30B-coder MoE accuracy fix — `MOE_USE_MICRO_GEMM_PREFILL=0` *(D4)*
- **What / where:** documented OVMS/2026.2 known limitation — *"Qwen3-MOE models like Qwen3-30B-A3B in int4 on GPU
  might have reduced accuracy with long prompts"*; workaround = OVMS launch env `MOE_USE_MICRO_GEMM_PREFILL=0`. (R4#1,
  corroborated R3#2.)
- **Benefit / measure:** names BlarAI's *exact* coder model (Qwen3-Coder-30B-A3B, INT4, GPU) and its trigger
  (long/repo-context prompts — the headless-coding-dispatch workload). The defect is silent (degraded code, not a
  crash). Measure: a fixed long-context coding eval with the flag on vs off; record the TTFT delta (the only cost).
- **Risk:** *"slightly increases TTFT."* No accuracy downside. CPU/non-INT4 unaffected.
- **Effort:** trivial (one env var on the OVMS launch). Ops/config change, not in-process code.
- **Scope fit:** this session (wire into the OVMS launch); the accuracy/TTFT delta is a Session-2 measurement.

### A5. Free-with-the-bump robustness (no/low code) — capture + optionally wire
- **Windows CRT memory-leak/crash fix** (core 2026.1) — directly relevant to a long-running in-process Windows host.
  Free; just inherit. (R2#9)
- **`COMPATIBILITY_CHECK` / `RUNTIME_REQUIREMENTS`** (core 2026.2) — a fail-closed pre-flight that a compiled blob is
  importable before load; clean fit for the signed-manifest boot posture. *Optional* small do-now wiring into boot. (R2#9)
- **`i64` attention-mask heap-overflow fix** (GenAI #3610) + **LTO-compiled GenAI binaries** (#3672) + **ICU-DLL removed
  from tokenization** (smaller footprint / faster startup) — all passive, inherited on upgrade. (R1#12,#10; R1-dedup)
- **`finish_reason` / `TOOL_CALL_STOP`** (GenAI #3670) — lets the AO tool loop know *why* generation stopped instead of
  inferring it. Low-moderate effort; **optional do-now** (cleaner control flow) or defer. (R1#6)
- **Scope fit:** the fixes are automatic; `COMPATIBILITY_CHECK` and `finish_reason` are optional small do-now items —
  your call whether to fold them in now or ticket them.

---

## B. MEASURE-IN-SESSION-2 (carry into the data-collection campaign)

These need the benchmark harness + hardware time, which is Session 2's job. Each is recorded here so the Session-2 brief
carries it with its benefit/risk/effort.

- **B1. EAGLE-3 vs the vanilla 0.6B draft** — 8B (and 14B if D1=yes), sweeping `num_assistant_tokens` 3–7: tokens/s,
  **acceptance length**, peak co-resident GiB. Calibrated expectation: modest on a bandwidth-bound iGPU (~1.3–1.8× over
  no-draft, possibly only marginally above the already-tuned 0.6B draft) — the honest result is the point. (R5)
- **B2. INT4 KV-cache quant sweep** (A3) — {FP16,INT8,INT4} × {16K,32K} prompts: peak RAM, TTFT, TPOT, quality. (R2#1)
- **B3. `min_p` A/B** (A1) on the AO eval set; **`guidance_rescale` A/B** (A2) on SDXL. (R1#1,#5)
- **B4. VLM slice-before-matmul + GPU Qwen3-VL perf** (PC4) — confirm #3640 engages (watch the compiled-model log) and
  measure Qwen3-VL-8B TTFT/TPOT/load 2026.1.0 vs 2026.2.1 on a fixed image+prompt set. (R1#4, R2#5, R1#8)
- **B5. 30B MoE accuracy fix delta** (A4) — code-eval + TTFT, flag on/off. (R4#1)
- **B6. GPU model-load speedup** — parallel cache-blob load (2026.2) + `CACHE_BLOB_ID` (2026.1): cold-vs-warm
  compile+load wall-time for the 14B and SDXL **with model caching enabled** (note: the code currently sets
  `CACHE_DIR=""` everywhere — enabling caching is itself the change; see C-row C7). (R2#3)
- **B7. chat-template perf metric** (GenAI #3469) — a previously-hidden host-side cost; feeds the community-grade
  dataset. Free telemetry. (R1#9)
- **B8. XAttention long-context TTFT** (preview, Xe2-supported) — TTFT vs context length, accuracy check. (R2#2)
- **B9. The two deferred 2026.1 caveats** carried per the brief: the cartoon **steady-state** contention re-run (warm
  the partner first) and the **bandwidth-unit (GB/s) confirmation** from Level-Zero docs.

---

## C. DEFER / FUTURE TICKET (larger or decision-class — not this session)

- **C1. EAGLE-3 (8B + 14B) — BLOCKED on conversion** *(D1)* — attempted this session with the now-correct
  optimum-intel v2.0.0 recipe; blocked by a structural checkpoint↔modeling mismatch (PC2). Future effort: file the
  upstream issue (lowest-leverage-cost), or wait for a fix / pre-converted IR, or write a key-remap shim. The
  vanilla 0.6B-draft spec-decode is unaffected and stays the production path. (`eagle3_conversion_findings_2026-06-29.md`)
- **C2. Data-aware AWQ requant of Qwen3-Coder-30B-A3B** — NNCF 3.0+ supports data-aware INT4 over MoE 3D-MatMul
  (AWQ/GPTQ/scale-estimation); a more thorough fix for the D4 accuracy issue than the env workaround. **Large**
  (calibration set + re-convert + eval, isolated venv). Ticket. (R2#6, R3#2)
- **C3. Qwen3.5 / Qwen3.6 / Coder-Next** *(D5, escalated — capability/quality decision)* — 2026.2 newly enables them on
  the GPU (the substrate signal the model-upgrade-watch waited on). But: **loses spec-decode** (no 3.5/3.6 EAGLE-3
  draft), hybrid-attention GPU-path maturity unproven, vendor quality claims unverified. Candidates: 3.5-9B
  native-MM (consolidate the 8B text + 8B VLM roles), 3.5/3.6-27B (quality lift for the 14B role, +memory),
  3.6-35B-A3B-MM (30B-coder successor, swap-in only). Keep on the watch; escalate any swap. (R2#4, R3#3/4/5)
- **C4. SDXL heterogeneous offload to the idle NPU** — assign the SDXL text-encoder/VAE to the (free, ADR-011-idle) NPU
  to cut GPU memory pressure during image gen — potentially avoiding the 14B eviction the hires path forces. Moderate;
  on-mandate (local). Worth a spike. Ticket. (R3#6)
- **C5. OpenSSF Model Signing (OMS / Sigstore `model-signing`)** — a standards-based, single-artifact model-signing
  scheme covering the multi-file IR layout; bare-key mode runs with no network (air-gap-safe). Strategic/AIGP-relevant
  replacement-or-augment for the hand-rolled signed-manifest. Medium; keep the manifest until OMS verify is proven
  equivalent. Ticket. (R4#4)
- **C6. OVMS serving knobs for the 30B** — `enable_prefix_caching=true` + static `cache_size` (agentic TTFT win) and
  INT8/INT4 KV-cache compression (`plugin_config`). Low effort, but a memory-sizing measurement against the shared
  pool first. Measure/ticket. (R4#2,#3)
- **C7. Enable GPU model caching (`CACHE_DIR`)** — the code sets `CACHE_DIR=""` (caching off) at every pipeline; enabling
  it + `CACHE_BLOB_ID` speeds every reload (the 14B reload after a hires eviction, VLM/SDXL on-demand loads). It's a
  behaviour change (compiled-blob disk writes, ~GBs; cache-invalidation on driver/model change). Decide the cache dir +
  measure (B6) before adopting. Ticket. (R2#3)
- **C8. OVMS loopback hardening** — API-key auth on `/v3`, explicit localhost bind, non-root, default SSRF restriction.
  Defense-in-depth even air-gapped (other local processes can reach the port). Low effort. Ticket. (R4#5)
- **C9. Gemma-4 evaluation** — 2026.2 newly enables Gemma 4 on GenAI, unblocking the in-tree
  `docs/MODEL_EVALUATION_GEMMA4_12B.md`. Note a **dense 12B is NOT on the official validated-size list**
  (E2B/E4B/31B/26B-A4B) — conversion/accuracy must be validated. Large eval. Ticket. (R1#2)
- **C10. NNCF sub-INT4 formats (NVFP4 / MXFP4)** — potential further weight shrink, but **GPU support is
  experimental** (CPU/Xeon-optimized); may upcast on Xe2 with no real win. Spike-first/watch. (R2#7)

---

## D. REJECT / NOT-APPLICABLE (listed with the reason, per the operator's instruction)

- **Linux-only mmap compile-time peak-memory reduction** (core 2026.2) — **Windows host**; the single highest-value
  memory item in 2026.2 that BlarAI **cannot** capture. (R2)
- **NPU `release-weights` memory reclamation** (2026.1) — NPU idle (ADR-011). (R2)
- **TaylorSeer feature-caching** (Flux/SD3/LTX) — **DiT-only**; BlarAI's SDXL is UNet → no effect unless the image model
  family changes (see C-row on SANA/SD3.5, declined as large). (R1,R2,R3)
- **Experimental Level-Zero (L0) GPU backend for Xe2** (2026.1 preview) — requires a **from-source build**, unsupported
  for production; against the fail-closed/decades-stable posture. Watch only. (R2#8)
- **OpenVINO backend for llama.cpp** (2026.1 preview) — different runtime ecosystem; no value to an in-process GenAI
  stack. (R2)
- **Video (T2V/LTX), Whisper, JS/Node pipelines, TTS** — no use case in BlarAI. (R1)
- **Models over the 31.323 GiB ceiling** — Qwen3-Next-80B-A3B (~40 GiB INT4), GPT-OSS-120B. Not runnable here. (R1,R3)
- **Speculators-format EAGLE-3 (`Eagle3Speculator`)** — unsupported by optimum-intel (PR #1468 closed unmerged); the
  on-disk `eagle3-qwen3-8b-raw` is this format → use AngelSlim instead. (R5)
- **OVSA (SGX/TEE license-server framework), HF model-download retry/resume, Docker resource auto-tuning, KServe/TFS
  input-validation hardening** — wrong shape for a single-user local box / air-gapped (models pre-staged) / not on the
  OpenAI-compatible `/v3` path BlarAI uses. (R4)
- **`add_extension` custom-op registration** (GenAI #2952) — loads arbitrary host code; keep unused under fail-closed
  (no current model needs it). (R1#11)
- **SANA / SD3.5-medium DiT image path** (would unlock TaylorSeer) — large: abandons the tuned SDXL+LoRA stack and
  re-tunes; only if SDXL speed/memory becomes a real pain (C4 addresses memory while keeping SDXL). (R3#7)

---

## 2. Behaviour-change watch (the one real one)

- **Multinomial sampling rework** (GenAI #3634, 2026.2.0) reorders sampling transforms (top_k→temperature→top_p) and
  defers `expf`. For `do_sample=true` (the **AO**), the token drawn for a given `rng_seed` **can differ from 2026.1.0**
  — i.e. exact sampled-output reproducibility vs the old version is not preserved, and any golden/snapshot test on
  *sampled* generations would need rebaselining. **Greedy (`do_sample=false` — the PA `/no_think` path) is unaffected.**
  The standing gate passed 4608/0 on the bump, so no such golden test is currently broken; flagged for awareness. (R1#3)

## 3. Sources

Per-candidate version + link are inline above. Primary trees: `openvinotoolkit/openvino.genai`,
`openvinotoolkit/openvino`, `openvinotoolkit/model_server`, `huggingface/optimum-intel`, `openvinotoolkit/nncf`
releases; the AngelSlim and OpenVINO HF orgs; the OpenVINO 2026.2 release notes. Full source lists are in the five
research transcripts retained for this session.
