# Qwen3.5-2B / 4B / 9B on this laptop: speculative decoding, vision, int4 vs int8

*Plain summary: a speed-up method now exists for all three models, but it needs an upgrade from the
installed OpenVINO 2026.2.1 to 2026.4.x, and nobody has measured whether it speeds anything up on
a laptop GPU like ours. All three models can read images and video; the 9B has an open bug that
gives wrong image descriptions on Intel GPUs.*

**Update 2026-10-04: Phase 1 (#1663) measured the 4B INT8 with MTP on this machine. The unmeasured
claims below about speed are now answered in `docs/research/qwen35-4b-mtp-phase1-verdict-2026-10-04.md` and
`PERFORMANCE_LOG.md`; the research text itself is left as written.**

Research only, 2026-10-03. Nothing was installed or run on this machine. Sources: Hugging Face
model files (config.json, weight indexes, file listings), OpenVINO and OpenVINO GenAI source at
each release tag, pull requests and issues read through the GitHub API, release notes. Two
research agents gathered it; every claim below is from source, merged code or a live API read
unless marked *(unverified)*.

## 1. Speculative decoding — is any method available?

Speculative decoding means a cheap guesser proposes the next few words and the big model checks
them all at once, which can be faster when the guesses are good.

**On the installed 2026.2.1: no.** These models mix two kinds of layers (three "linear attention"
layers to every one normal layer). To check guesses, the runtime has to be able to rewind the
linear layers' state when a guess is rejected. That rewind code is absent from the 2026.2.1 and
2026.3.0 source and first appears in 2026.4.0.

**On 2026.4.x (2026.4.1 released 2026-10-01): yes, one method is solid.**

| Method | 2B | 4B | 9B | Status on 2026.4 |
|---|---|---|---|---|
| Multi-Token Prediction (MTP) — the model's own built-in guesser head | head present | head present | head present | Merged (GenAI #4065), tested in CI on a Qwen3.5 model, Intel's published int4/int8 files include the head (re-published 2026-09-25). Greedy only; prefix caching must be off. |
| DFlash (separate small guesser model) | no guesser published | `z-lab/Qwen3.5-4B-DFlash` | `z-lab/Qwen3.5-9B-DFlash` | In 2026.4 release; GPU labelled "Preview". |
| EAGLE-3 (separate guesser model) | none | community only | community only | Not supported for these mixed-layer models yet (open draft #4401). |
| Smaller Qwen3.5 as guesser (e.g. 0.8B guessing for 9B) | same vocabulary | same | same | Not tested upstream for Qwen3.5; the guesser side has no rewind handling. Unproven. |
| Prompt lookup (no guesser; copies from the prompt) | yes | yes | yes | Supported for mixed-layer models in 2026.4, tested on other models, not Qwen3.5. |

**Measured speed-ups that exist anywhere:** 2B with MTP on a desktop CPU, 1.07×–1.30× over three
prompts. 27B with MTP on a discrete Intel Arc Pro B70: 3.4× faster at short context, 3.1× *slower*
at 98K tokens. **Nothing for Lunar Lake / Arc 140V.** The closest is an open report (openvino
#38153) on the sibling Arc 140T integrated GPU with 9B int4: checking 3 guessed tokens takes
113 ms against 78 ms for one normal step at 8K context, because the GPU falls back to a slower
kernel for 2–4-token batches. If that holds here, MTP may give little or nothing until that
kernel is fixed. **Only a measurement on this machine settles it.**

Costs that come with it: prefix caching must be off (multi-turn chats re-read the history), and
only greedy (deterministic) decoding is allowed — which BlarAI already uses.

## 2. Multimodal — and is it available here?

**All three are natively multimodal: text, images and video. No audio.** The vision encoder ships
inside the one checkpoint; there is no separate "VL" version.

| | 2B | 4B | 9B |
|---|---|---|---|
| Vision in OpenVINO GenAI on GPU | since 2026.2.0 — **available on the installed version** | same | same |
| Known GPU problems | int8 crashed on long prompts (#36151, fixed in 2026.3 dev; whether 2026.2.1 has the fix is *unverified*) | same | same, **plus #37223 (open): wrong-but-plausible image descriptions on Intel integrated GPU; correct on CPU. Intel reproduced it; int8 did not fix it.** Untested on our 140V. |
| Text-only answers affected by #37223? | — | — | not shown to be |

Caveats: the current Intel-published files say they need 2026.4; the June versions are needed for
2026.2.1. Qwen3.5's `/no_think` prompt text reportedly does not work (a third party on an Arc 140V
measured *more* thinking with it). ~~Relevant because the Policy Agent depends on it.~~ **Corrected
the same evening:** the Policy Agent does not use `/no_think`; it pre-fills a closed empty think
block with `apply_chat_template=False` (`evals/hardware_pipeline.py:155–178`, lesson 369), and the
Qwen3.5-4B chat template's own `enable_thinking=false` emits exactly that block (template read
2026-10-03). Not a blocker; Phase 1 (#1663) witnesses the first generated token.

## 3. int4 vs int8 — memory, speed, precision

Published Intel file sizes (GiB, whole model including vision and MTP head):

| | 2B | 4B | 9B |
|---|---|---|---|
| fp16 (full precision reference) | 5.22 | 9.90 | 18.02 |
| **int8** | **2.63** | **4.98** | **9.04** |
| **int4** | **1.99** | **3.33** | **5.85** |
| of which vision part (kept int8 in both) | 0.31 | 0.31 | 0.42 |

For scale: today's resident Qwen3-14B brain is larger than any of these at int4.

**Precision:** no published int4-vs-int8 accuracy numbers exist for the OpenVINO files. The
nearest: Qwen3.5-4B on NVIDIA hardware, plain int4 lost 2.8 points on a general-knowledge test
(MMLU, 76.3 → 73.5) while int8 lost 0.4 (→ 75.96). Smarter int4 recipes (AWQ, AutoRound) recover
most of the gap. Intel's int4 files use the plain recipe.

**Speed:** no published tokens-per-second for any of the three on an Arc 140V. On a memory-bound
integrated GPU, int4 is normally faster than int8 because fewer bytes cross memory per token —
*expected, not measured here*.

**The trade in one line:** int4 ≈ 35–40% less memory than int8 and likely faster; int8 is closer
to full quality. On this machine int8 also carries the long-prompt crash risk on 2026.2.1.

## 4. What would settle it

All three questions end in the same place: one measured run on this laptop, on 2026.4.1, per
size × {int4, int8} × {MTP off, on}, with the n≥3 / variance-first protocol (#1662's method), plus
an image-description check for the 9B against #37223. Upgrading the runtime is already planned
under epic #1610 (S2/S3½); this work fits there.

## Correction to an existing document

`docs/research/openvino-2026.4-relevance-assessment-2026-09-21.md` (line ~225) treats upstream #4476 as
an open greedy-divergence bug. It is **closed**: it concerned Qwen3-8B with a 0.6B draft, and the
cause was KV-cache and dynamic quantization, fixed by setting `KV_CACHE_PRECISION=f16` and
`DYNAMIC_QUANTIZATION_GROUP_SIZE=0`. A related issue, #4367 (stateful vs continuous-batching
output differing), is still open.
