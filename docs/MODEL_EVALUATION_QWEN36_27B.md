# Model Evaluation — Qwen3.6-27B / ThinkingCap-Qwen3.6-27B as Qwen3-14B successor

**Date:** 2026-07-08 · **Status:** EVALUATED — NOT RECOMMENDED YET (two concrete revisit triggers below)
**Question:** Can Qwen3.6-27B (base, or the BottleCapAI "ThinkingCap" fine-tune) replace Qwen3-14B
as the BlarAI resident brain on the Arc 140V, and could it also absorb the separate Qwen3-VL-8B
vision model? Could DFlash give it speculative decoding on this device?

---

## Verdict in one paragraph

It **runs** on our exact stack today (OpenVINO GenAI 2026.2.1, which BlarAI already ships, supports
Qwen3.6-27B on GPU; official Intel-validated INT4 weights exist at ~15.7 GB — fits the 31.323 GB
ceiling standalone). It **is natively multimodal** — one model would replace both Qwen3-14B and
Qwen3-VL-8B, killing the vision-model load/evict churn. But the swap **loses speculative decoding
entirely** (our current ~1.5–2× throughput lever): DFlash is a CUDA/vLLM/SGLang-world technique
with no OpenVINO support, no OpenVINO IR, and no tracked integration; no classic or EAGLE-3 draft
compatible with Qwen3.6's vocabulary exists anywhere. On top of that, the 27B is **dense** (~2×
the per-token compute of the 14B on the same iGPU) and there is an **open correctness bug** —
openvino.genai **#3870**: Qwen3.6-27B producing incoherent output on OpenVINO GenAI. Net expected
generation speed: roughly **3–4× slower than today's 14B+draft** (estimate, unmeasured on the
140V), with an unresolved coherence risk. Not a viable resident-brain swap as of 2026-07-08.

## What changed since the last look (2026-06-29 watch entry)

- Then: "runnable but loses spec-decode." **Still true — nothing on the spec-decode front has
  shipped for our stack.** DFlash's existence does NOT change this: its drafter
  (`z-lab/Qwen3.6-27B-DFlash`, ~2B BF16) is a block-diffusion model with KV-injection that only
  vLLM / SGLang / Transformers / MLX can run. llama.cpp's attempt is broken (llama.cpp #25116).
- New negative signal: **openvino.genai #3870** (Qwen3.6-27B/35B incoherent output on GenAI).
- New architectural fact: in OpenVINO GenAI, Qwen3.6-27B is a **VLMPipeline** model, not a text
  LLMPipeline model. BlarAI's `SharedInferencePipeline` (PA+AO brain) is built on LLMPipeline
  with a draft model attached; VLMPipeline is the API `shared/inference/vlm.py` uses and has **no
  speculative-decoding support at all**. A swap is therefore a plumbing rework, not a model-dir
  config change.

## Key facts (verified 2026-07-08, sources at bottom)

| Dimension | Finding |
|---|---|
| Architecture | DENSE 27B (not MoE). Hybrid: 64 blocks, 16 full-attention + 48 Gated-DeltaNet linear-attention. 262K native context. Vocab 248,320 (≠ Qwen3's ~152K — why no existing draft pairs). |
| Multimodal | YES, native image+video+text in the base repo (no separate -VL variant). Would absorb Qwen3-VL-8B. |
| OpenVINO weights | `OpenVINO/Qwen3.6-27B-int4-ov` (official org), INT4_ASYM g128, ~15.7 GB, floor "2026.2.0+". |
| Pipeline class | **VLMPipeline** (image-text-to-text) in GenAI's supported-models list — NOT text LLMPipeline. |
| Spec-decode | NONE possible today. DFlash = OpenVINO-unsupported; no Qwen3.6-vocab classic draft exists; no Qwen3.6 EAGLE-3 draft exists (SpecForge RFC #486 is an *open request* to build the training infra). |
| KV cache | Favorable: only 16/64 layers grow KV; DeltaNet layers hold fixed state → ~¼ the KV growth. Long context is the one place this model is *cheaper*. |
| Known bugs | openvino.genai #3870 (incoherent output, our exact stack); OV #36187 is dual-GPU-only (single-GPU reported fine). |
| Perf on Arc 140V | UNMEASURED. Intel's AI-PC demo used the 35B-A3B MoE (~3B active); the 27B dense has 27B active — materially heavier per token. |
| License / thinking | Apache 2.0; Qwen3-style `<think>` mode with disable toggle (our /no_think PA posture maps over). |

## ThinkingCap-Qwen3.6-27B specifically

- Legitimate, **architecturally unchanged** fine-tune (`Qwen3_5ForConditionalGeneration`, identical
  config to base) → converts to OpenVINO IR INT4 via `optimum-cli export openvino` exactly as the
  base does. No OpenVINO conversion published yet — we would be first (a ~54 GB BF16 download +
  throwaway-venv conversion; josefprusa's INT4 AutoRound quant at ~15 GB confirms the size class).
- What it does: reasoning **token-efficiency** RL — ~46% fewer thinking tokens at −0.7pt
  out-of-domain accuracy (80.7 vs 81.5), +1.0pt in-domain. Vision and thinking mode preserved.
  Apache 2.0. Safety guardrails preserved (it is NOT an uncensored tune).
- Why it's the *interesting* variant: cutting ~46% of thinking tokens is a real wall-clock win
  that would partially offset the lost speculative decoding — but only partially, and only on
  thinking-heavy turns. It does not change any blocker above.
- Reputation: small company (BottleCapAI), modest downloads, high like-ratio, positive signal from
  known local-LLM figures, several independent re-quants. No deep community review corpus yet.

## Why we keep "forgetting" why we can't use these

The answer moved. Pre-June-2026 it was "OpenVINO can't run the Qwen3.5/3.6 generation at all"
(true then, stale now). Since OV 2026.2 the durable answer is:

1. **No speculative decoding exists for Qwen3.6 on OpenVINO** — the drafts don't exist for its
   vocabulary, DFlash is CUDA-stack-only, and VLMPipeline (which Qwen3.6 requires) has no
   spec-decode at all. Our 14B+draft is faster than a 27B could be here.
2. **27B dense ≈ 2× the per-token compute of 14B** on the same iGPU — the opposite direction from
   the MoE models the headlines benchmark.
3. **Open coherence bug (#3870)** on exactly our runtime.
4. **Plumbing:** the swap is a SharedInferencePipeline→VLMPipeline rework + ADR-012 amendment +
   full GPU re-validation, not a config flip.

## Throughput estimate (2026-07-08 addendum — the 11 tok/s question)

Operator decision rule: >11 tok/s → schedule an official test plan. **Estimate: ~5.5–7 tok/s —
threshold unreachable, no test plan scheduled.**

Basis: decode on the Arc 140V is memory-bandwidth-bound. Calibrated from this repo's own
measurements (PERFORMANCE_LOG.md 2026-06-28): Qwen3-14B INT4 spec-off 11.1 tok/s over ~8 GB
weights and Qwen3-8B INT4 spec-off 19.8 tok/s over ~4.6 GB both imply the same ~90 GB/s effective
bandwidth. Qwen3.6-27B INT4 streams ~14 GB/token (dense — no MoE sparsity to escape it; the
DeltaNet hybrid reduces KV growth, not weight streaming) → 90/14 ≈ 6.4 tok/s central estimate.
Hard ceiling: LPDDR5X theoretical max ~136 GB/s → even at impossible 100% efficiency the cap is
~9.7 tok/s. **11 tok/s is above the physical ceiling for a dense 27B at INT4 on this device.**
ThinkingCap's ~46% thinking-token cut improves wall-clock-to-answer on reasoning turns (≈ parity
with the 14B spec-OFF), but stays ~1.4× slower than the production 14B spec-ON and ~2.5× slower
on non-thinking turns. Spec-decode is the only lever that beats the bandwidth wall — hence the
revisit triggers below are unchanged.

## Revisit triggers (updated 2026-07-08 evening after reading the upstream threads)

1. **Spec-decode — TWO upstream tracks now open, and the MTP one is closer to landing
   (2026-07-09 addendum, see §MTP below).**
   (a) **Native MTP** (multi-token prediction): Qwen3.5/3.6 ship a built-in MTP head in the
   base weights — the model drafts its OWN next tokens, no external draft model, which
   dissolves the "no draft exists for the 248K vocab" blocker entirely. Watch
   **openvino.genai PR #4065** ("Qwen35 MTP Support" — open, Intel author apaniukov, active
   as of 2026-07-09) + **optimum-intel PR #1814** (exports the MTP head; its own example
   exports **Qwen3.6-35B-A3B**, so the track covers the Qwen3.6 family, not just 3.5). The
   MTP *infrastructure* already merged via the Gemma4 MTP stateful PR **#3958**
   (2026-07-02). llama.cpp has shipped this since b9180 (May 2026) with measured 1.25–2.7×
   task-dependent speedups on Qwen3.6-27B.
   (b) **DFlash — watch openvino.genai #3938** ("Enable DFlash with support of Qwen3.6",
   open, claims up to 2.1x in continuous batching; export rides optimum-intel PR #1756) —
   requires the separate `z-lab/Qwen3.6-27B-DFlash` drafter; strictly heavier path than (a).
   Either merging → re-measure. Note the MTP caveat below: on THIS device the Stage-1
   bottleneck is compute-bound DeltaNet kernels, not bandwidth, so spec-decode gains stay
   capped until trigger 3 also moves.
2. ~~#3870 closes~~ — **MOOT**: closed 2026-06-08, conversion-side root cause, official weights
   unaffected (our run confirms, short prompts). Replaced by: **long-prompt coherence verify**
   (~1K-token prompt through the harness) as a Stage-2 precondition.
3. **GPU-plugin kernel maturity** for the Gated-DeltaNet hybrid: re-run
   `scripts/benchmark_vlm_text_inference.py` at each OpenVINO version bump. Mechanism leads:
   openvino.genai **#3773** (closed experiment: hybrid models fall back to SDPA — plausibly why
   our prefill collapsed 9x) and openvino **#36270** (open: Qwen3.6-35B MoE slow on integrated
   Arc; unfused MoE-MLP kernels; our dense datapoint is complementary evidence).
4. **openvino.genai #3937 — TESTED SAME-DAY on our hardware: REPRODUCED on the 27B, and it is
   now the HARDEST swap blocker.** Probe (`scripts/probe_qwen36_thinking_toggle.py`, evidence
   `docs/performance/qwen36_27b_thinking_toggle_probe_2026-07-08.json`): (a) plain prompt →
   thinking narration; (b) **`/no_think` soft switch → IGNORED** — the model *acknowledges the
   constraint inside its own thinking trace* and thinks anyway (the production PA mechanism,
   ADR-012 §2.4, is broken on this model); (c) `generate(enable_thinking=False)` → **accepted by
   the GenAI API, ignored by the model** (the exact #3937 symptom, previously reported only on
   the 35B; ours is on release 2026.2.1 + official OpenVINO INT4, not nightlies). Aggravating:
   the thinking is **untagged** (no `<think>` wrapper in output), so the AO's tag-based
   think-strip cannot even hide it. At 3.6 tok/s every PA classification would pay a
   multi-hundred-token silent detour → disqualifying for the PA role until resolved (may be
   template-side in the IR export — watch #3937). Re-probe alongside the throughput re-measure
   at each version bump.

Any of 1/3 firing → re-measure; a swap additionally requires the long-prompt coherence check
(2), the #3937 thinking-toggle check (4), and the VLMPipeline plumbing scope, then an ADR-012
amendment. The consolidation upside (one model = brain + vision) is real and stands ready.

## Stage-1 RESULT (2026-07-08 — MEASURED; supersedes the estimate for this stack version)

Run same-day on the Arc 140V (exclusive GPU, battery-campaign-coordinated). Full entry:
`PERFORMANCE_LOG.md` 2026-07-08; JSON with all output texts:
`docs/performance/benchmark_vlm_text_qwen3.6-27b-int4-ov_2026-07-08_16-21-18.json`.

- **Pass criterion 1 (loads + generates inside ceiling): PASS** — 15.9 GB GPU-committed,
  min 8.56 GB system-available, 0 errors, clean teardown.
- **Pass criterion 2 (coherence / #3870): PASS, with a scope correction (same-day, from reading
  the actual thread):** all 20 outputs fully coherent on OV GenAI 2026.2.1 + driver
  32.0.101.8826 + the official INT4 build. HOWEVER: #3870 was **CLOSED 2026-06-08** upstream —
  root cause was a broken optimum-intel conversion recipe (ignored_scopes removed) affecting
  SELF-converted models, plus a reporter-side GPU-compiler/driver update; correctly-converted
  models (like the official OpenVINO org build we ran) were never affected. Also: the reported
  failure mode was **long-prompt-dependent** (fine ≤~20 tokens, breaking at 60–80+), and our
  benchmark prompts are short — so our run proves short-prompt coherence only. **Long-prompt
  coherence (production system prompt is ~840–970 tokens) is an explicit Stage-2 check**, not
  proven here.
- **Pass criterion 3 (decode ≥ ~5 tok/s): FAIL** — **3.59 tok/s median sustained** (short
  answers 5–6). Prefill 219 pp vs the 14B's ~1960 reveals the cause: the Gated-DeltaNet hybrid
  runs on unoptimized GPU-plugin kernels — compute-bound, not bandwidth-bound. This is a
  SOFTWARE deficit (physics ceiling ~9.7 unchanged); expect movement across OpenVINO releases.
- **Net:** below the LA-accepted ~6.5 tok/s floor → Stage 2 (ThinkingCap conversion + quality
  evals + plumbing scope) NOT triggered. New cheap standing check: re-run
  `scripts/benchmark_vlm_text_inference.py` (weights stay resident on disk) at each OpenVINO
  version bump; kernel-optimization progress is now revisit trigger (c) alongside (a)/(b) below.

## Stage-1 smoke-eval test plan (2026-07-08 — LA-approved)

**Decision context:** the LA accepted ~6.5 tok/s as a viable speed for the capability gain
(in-chat, 2026-07-08), which moves the blocker from throughput to (a) the #3870 coherence bug and
(b) the VLMPipeline plumbing rework. Stage 1 settles (a) and replaces the estimate with a
measurement. The original ">11 tok/s" rule is superseded by this acceptance.

**Scheduling note:** the M2 battery campaign owns the overnight GPU window (Task Scheduler
`\BlarAI\BlarAI-M2-Battery-Nightly`, 23:00 guarded, 0/4 passes banked) — Stage 1 runs DAYTIME,
leaving the campaign untouched.

| Item | Plan |
|---|---|
| Model under test | `OpenVINO/Qwen3.6-27B-int4-ov` (official Intel-validated INT4, ~15.7 GB). Base model, NOT ThinkingCap — identical architecture means speed transfers exactly; converting ThinkingCap is Stage 2, gated on Stage 1 passing. |
| Harness | `scripts/benchmark_vlm_text_inference.py` (new) — VLMPipeline text-only; prompt set v1 + pp probe pp-v1 byte-identical to `benchmark_gpu_inference.py`, 5 measured + 2 warmup, greedy, 30 s cooldown → directly comparable to the standing 14B/8B rows. |
| Preconditions | BlarAI app closed + AO stopped; ≥20 GB system-available (script guard ABORTS below the floor — the 2026-06-21 pre-load-gate lesson); battery campaign not in-window. |
| Measures | decode tok/s (median/mean/P95), TTFT, prefill pp tok/s, load time, memory (before/after/min-during), full output texts. |
| #3870 check | every generated text captured in the result JSON; coherence judged from the captured outputs (reviewer, not script). Incoherent output = FAIL regardless of speed. |
| Pass criteria | (1) loads + generates without error inside the 31.323 GB ceiling; (2) outputs coherent (no #3870 reproduction); (3) measured decode ≥ ~5 tok/s (sanity vs the 5.5–7 estimate — a wildly lower number means something is misconfigured, not that the estimate was wrong). |
| Recording | community-grade: PERFORMANCE_LOG.md entry + `docs/performance/benchmark_vlm_text_*.json` (NOT-measured list embedded in the JSON). |
| Stage 2 (only if Stage 1 passes) | convert `bottlecapai/ThinkingCap-Qwen3.6-27B` to OV INT4 (throwaway venv, `optimum-cli export openvino`, NNCF INT4_ASYM g128 to match the official recipe), re-run this harness + the answer-quality eval suite, scope the SharedInferencePipeline→VLMPipeline rework, then put the swap decision to the LA as an ADR-012 amendment. |

## MTP — native multi-token prediction (2026-07-09 addendum)

Surfaced by the LA via `froggeric/Qwen3.6-27B-MTP-GGUF`: Qwen3.6 carries a **native MTP
(multi-token prediction) head in its base weights** — self-drafting speculative decoding with
no external draft model. This was NOT usable in our 2026-07-08 Stage-1 run and would not have
changed its numbers:

- **Released OpenVINO GenAI 2026.2.1 has no MTP support** — it lands via PR #4065 (open) on
  top of the merged Gemma4 MTP infra (#3958, 2026-07-02), with export via optimum-intel
  PR #1814 (open).
- **The official `OpenVINO/Qwen3.6-27B-int4-ov` weights we benchmarked do not include an
  exported MTP head** — a post-#1814 re-export would be required.
- **Device-fit caveat:** MTP's win is amortizing weight streaming (bandwidth-bound decode).
  Our Stage-1 result showed the 27B is currently **compute-bound** on unoptimized
  Gated-DeltaNet GPU-plugin kernels (3.59 tok/s, prefill 219 pp) — verifying K drafted tokens
  per pass re-pays most of that compute, so expect MTP's realized gain here to be well below
  llama.cpp's published 1.25–2.7× until the kernel deficit (trigger 3) closes. Sequencing:
  kernels first, then MTP multiplies what's left.
- **Unchanged blockers:** #3937 thinking-toggle (hardest), VLMPipeline plumbing rework,
  long-prompt coherence check. MTP removes only the "no spec-decode possible" leg.

Standing check addition: at each OpenVINO version bump, alongside the throughput re-measure,
check whether #4065/#1814 shipped in the release; if yes, re-export INT4 with the MTP head and
benchmark with `draft_model` pointed at the model's own directory (the #4065 API shape).

## Sources

- https://huggingface.co/Qwen/Qwen3.6-27B · https://qwen.ai/blog?id=qwen3.6-27b
- https://huggingface.co/OpenVINO/Qwen3.6-27B-int4-ov
- https://huggingface.co/bottlecapai/ThinkingCap-Qwen3.6-27B · https://www.bottlecapai.com/thinkingcap-qwen3-6-27b
- https://huggingface.co/josefprusa/ThinkingCap-Qwen3.6-27B-int4-AutoRound-v1
- DFlash: https://arxiv.org/html/2602.06036v2 · https://github.com/z-lab/dflash · https://huggingface.co/z-lab/Qwen3.6-27B-DFlash
- https://openvinotoolkit.github.io/openvino.genai/docs/supported-models/
- https://github.com/openvinotoolkit/openvino.genai/issues/3870 · https://github.com/ggml-org/llama.cpp/issues/25116
- https://github.com/sgl-project/SpecForge/issues/486 · https://github.com/openvinotoolkit/openvino/issues/36187
- https://medium.com/openvino-toolkit/running-qwen3-6-35b-a3b-on-an-ai-pc-openvino-2026-2-brings-a-new-local-multimodal-llm-experience-e3a09aa26103
- NYU-RITS RTX 3090 demo: https://rits.shanghai.nyu.edu/ai/luce-dflash-brings-2x-speculative-decoding-to-qwen3-6-27b-on-a-single-rtx-3090/
- MTP (2026-07-09): https://huggingface.co/froggeric/Qwen3.6-27B-MTP-GGUF ·
  https://github.com/openvinotoolkit/openvino.genai/pull/4065 (Qwen3.5/3.6 MTP, open) ·
  https://github.com/openvinotoolkit/openvino.genai/pull/3958 (Gemma4 MTP infra, merged 2026-07-02) ·
  https://github.com/huggingface/optimum-intel/pull/1814 (MTP export, open; example covers Qwen3.6-35B-A3B)
