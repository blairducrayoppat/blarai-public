### 2026-06-27 — The style pack that ate the prompt

The operator wanted illustrations. He already had `/imagine` for photoreal SDXL, and he
remembered a second model — "playground" — that was meant to do flat, brochure-style
artwork. Playground v2.5 had been abandoned weeks earlier because it produced cluttered,
painterly backgrounds when what he wanted was clean flat-vector. So the ask was simple on
its face: give me a command that makes illustrations, and replace the dead playground model
with the proper one. He marked it critical.

The plan I pitched, and he approved, was the obvious one: take base SDXL, fuse a flat-vector
LoRA into the weights so the style is *baked in*, quantize the result to INT8, and ship it as
a second model behind a new `/illustrate`. "The new model with the flat pack baked in like you
suggest" — his words, my plan. It was wrong, and it took me most of a day to find out why.

The export fought me first, which is normal and forgettable: optimum couldn't infer the task
(fixed with `--task text-to-image`), then threw a "None repo 404" that I eventually traced to
the text encoders being written out as PEFT adapter shards with no `config.json` — because I had
dropped the `unload_lora_weights()` call after `fuse_lora()`, so diffusers still thought the
encoders carried live adapters. Annoying, mechanical, fixed. But fixing the export did not fix
the *images*. With a clean fused INT8 model in hand, I asked it for a coffee cup and got back a
gorgeous, confident, flat-styled blob that was not a coffee cup. Ask for a robot, get a
different blob. The model had learned the style so hard it had stopped listening to the prompt.
I tried the usual knobs — fuse the unet only, drop `lora_scale` to 0.5 — and the images stayed
coherent and stayed deaf.

The thing that cracked it was a control, not another knob. I ran a known-good finetune —
RealVisXL, the photoreal model that already works — through the *exact* same convert → INT8 →
generate harness. It produced perfect, prompt-faithful images. So the harness was clean; the
problem was specific to what I was feeding it. Then I generated from base SDXL with **no LoRA at
all** and just a flat-style *prompt* ("vector illustration of …, flat design, bold outlines,
solid color background") — and got exactly the crisp flat-vector illustrations the operator
wanted, fully prompt-faithful. The variable was isolated to one thing: the fusion itself.

The why, which a research pass confirmed: fusing a strong style LoRA algebraically overwrites
the cross-attention weights that carry text conditioning. The model ends up "knowing" the style
so completely that the prompt can no longer steer it — coherent, but unconditioned. INT8
data-free quantization makes it worse, injecting outliers into weights that have already been
smashed together. A clean finetune like RealVisXL survives the identical pipeline because its
weights were *trained* into coherence, not summed into it. Coherent output had fooled me for
hours into thinking the model was *almost* working and just needed tuning. It wasn't almost
working. It was failing in the one way that looks like success.

So the product changed shape, for the better. There is no fused model. `/illustrate` is base
SDXL 1.0 plus a flat-vector prompt template — no adapter at all, the fastest path (39.8 s cold),
and prompt-faithful. `/cartoon` is base SDXL plus the DoctorDiffusion vector LoRA applied **at
runtime** through `ov_genai.AdapterConfig` (alpha 0.8, **never fused**) — the adapter blends as a
generation-time influence, so conditioning survives and the alpha stays tunable. `/imagine` is
unchanged photoreal RealVisXL. Three commands, three genuinely distinct outputs (the operator
eyeballed the test renders and signed off on keeping both new styles selectable per-image rather
than as a config swap). The trade I took and own: the runtime-adapter cartoon costs ~20 s more
per generate than the prompt-only illustration (60.6 s vs 39.8 s cold), because the adapter
compiles and blends at generation time instead of being pre-baked. I accepted that latency
without hesitation — a fused model that ignores the prompt is worth zero; a slightly slower model
that listens ships. The rejected alternative (keep fusing, keep tuning) had no working version at
the end of it.

One governance note, decided with the operator and recorded on #703: these two styles do **not**
carry the content-attestation go-live ceremony that the uncensored photoreal model carries. His
reasoning — the illustration/cartoon base is not an uncensored finetune, so there is nothing for
that specific gate to attest. What stays, and is non-negotiable, is the cryptographic spine:
`require_signed_manifest=true` so the detached `manifest.json.sig` must verify at load, and a
SHA-256 integrity pin on the cartoon LoRA that is checked before the runtime adapter is ever
applied. Dropping a governance step that attests nothing, while keeping every integrity control
that actually defends the weights, is the right shape — relax what is theater, keep what is load-
bearing.

Shipped on `feat/703-illustrate-cartoon`: the standing gate is green (4606 passed / 0 failed),
the WinUI desktop build is clean (0 warnings / 0 errors), and the live-verify generated all three
styles on the real Arc 140V through the production path with the signed manifest verified and the
LoRA hash pinned — `is_available=true` for each, three distinct images saved.

**Proposed lesson:** *Coherent is not conditioned.* When a generative model produces confident,
plausible output that ignores the input, suspect the weights, not the prompt — and prove it with a
control, not another knob: pass a known-good model through the *identical* harness. If the
known-good model behaves and yours doesn't, the harness is innocent and the variable is whatever
you did to the weights. The corollary for diffusion specifically: do not fuse a strong style LoRA
into a base you intend to prompt — fusion overwrites the cross-attention that carries
conditioning (and INT8 quantization compounds it); apply the adapter at runtime instead, where it
influences without silencing.

**Next:** isolate the steady-state generate-only latency per style (warm pipeline, no eviction
between runs) and sample the resident footprint of the runtime-LoRA path, to publish a
generate-only + memory companion to today's cold end-to-end numbers; and remove the now-vestigial
`image_gen_model_variant` config key (tracked as a hardening follow-up on #703).

*(commits `<this>` on `feat/703-illustrate-cartoon`: image_gen runtime-adapter + per-style config; IPC `style` field; AO per-request style→config; gateway `/illustrate`+`/cartoon`; WinUI passthrough; base-SDXL illustration model + DD-vector LoRA + signed manifest. Gate 4606/0; WinUI 0/0; Arc 140V live-verify n=1 per style, production settings — cold E2E 43.8 s / 39.8 s / 60.6 s.)*
