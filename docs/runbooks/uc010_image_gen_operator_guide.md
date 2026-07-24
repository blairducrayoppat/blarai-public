# BlarAI Image Generation — Operator Guide

UC-010 Local Generative Imaging (ADR-033). A plain-language reference for the
operator: what the commands do, the **bounds** that aren't obvious, what the
models are good and bad at, and the tuning knobs. Written for a non-developer.

> Companion docs: `uc010_image_gen_go_live.md` (the one-time activation ceremony)
> and `services/assistant_orchestrator/config/default.toml` `[image_generation]`
> (the live knobs). This guide is the day-to-day "how do I get a good image" reference.

---

## 1. The commands

| Command | What it does | Notes |
|---|---|---|
| `/imagine <prompt>` | Text → image, from scratch | Your main tool. Photoreal. |
| `/illustrate <prompt>` | Text → **crisp flat-vector illustration** | Uses a separate illustration model. Just describe the subject — the flat style is added for you. |
| `/cartoon <prompt>` | Text → **soft cartoon** | Same model as `/illustrate` plus a style adapter applied at runtime. If the adapter cannot load it falls back to the flat-vector look rather than failing. |
| `/images` | List / delete stored images | Housekeeping for the encrypted image store. |
| `/edit <seed> <prompt>` | Image + text → image (img2img) | `<seed>` is a **local** image — a `blarai-img://<id>` reference, an absolute local file path, or a bare filename under `userdata/`. **Never a URL** (image generation does zero network egress — a URL seed is refused). A prompt must follow the seed. |
| `/save <id> <path>` | Writes the decrypted PNG to a local file | This is how you get an image out of the encrypted store to view it. `<id>` is the 32-character id from the `blarai-img://…` reference (or the full reference). Refuses network/UNC destinations. |

Every generated image is referenced as `blarai-img://<32-hex-id>` and stored
**born-encrypted** — it only becomes a plain file when you explicitly `/save` it.

---

## 2. Prompt bounds — the single most important thing to know

- **\~77 tokens ≈ 50–60 words is the hard ceiling.** The model (RealVisXL, an
  SDXL-family model) reads only the first \~77 tokens through each of its two text
  encoders. **Everything past that is silently dropped** — no error, it just
  never reaches the model. This is exactly why an early lunar prompt lost its
  "two aliens": they sat in the back third of a \~95-word prompt and were never read.
- **Front-load the must-haves.** Put the hardest-to-get elements (unusual poses,
  secondary subjects, the main subject) in the first \~40 words.
- **No weighting syntax.** This pipeline does **not** understand the `(thing:1.4)`
  emphasis syntax you may have seen elsewhere — it would be read as literal text.
  To emphasize something, use **word order and prominence words** instead:
  "in the foreground," "prominent," "large," not "in the background."

---

## 3. What the model is good and bad at

| Strong at | Weak at — and the fix |
|---|---|
| Single photoreal subjects | **Multiple distinct subjects** — it tends to drop or merge a secondary one. Fix: describe each concretely, place them "in the foreground," and re-roll a few times (generation is random — some seeds include them, some don't). |
| Faces that **fill the frame** — portraits and close-ups look excellent | **Small faces in wide shots** — a face that's only \~50 pixels in a 1024² frame has too few pixels and comes out mushy. Fix: frame the subject closer. (Hires-fix was the other remedy, but it is **off by default** for memory reasons — §6.) |
| Realistic scenes, materials, lighting, fabric | **Abstract / unknown things** ("aliens of an unknown species") — with no strong mental image it substitutes humans or sci-fi clichés. Fix: describe them concretely ("tall grey-skinned humanoids with smooth elongated heads and large black almond-shaped eyes"). |
| Photorealism (`/imagine` uses a photoreal model) | **Named characters.** "flying like Superman" made it draw the *actual* Superman, cape and all. Fix: describe the *look and pose*, never name a character. **For cartoons, don't fight `/imagine` — use `/cartoon` or `/illustrate`**, which run a different model built for it (§1). Cartoon subjects asked of `/imagine` come out painterly/realistic. |

---

## 4. When to use `/edit` (the non-intuitive one)

`/edit` re-renders an existing image while keeping its rough composition. It is
best for **changing the look, not the content**:

- ✅ **Good for:** lighting and mood (golden hour, dramatic shadows), color
  shifts, texture/style changes, small surface tweaks to what's already there.
- ❌ **Poor for:** *adding* a new subject ("add two aliens"), *changing* a pose or
  the layout, or fixing a structural problem. Those need a fresh `/imagine` —
  img2img preserves the seed image's structure, so it can't invent new things or
  rearrange the scene.

**Rule of thumb:** if the change is *"make this scene look different,"* use
`/edit`. If it's *"make a different scene,"* use `/imagine`.

---

## 5. Tuning knobs

Live in `services/assistant_orchestrator/config/default.toml` under
`[image_generation]`. **Edit, then restart the backend** to apply. These are
quality/behavior dials — none change what the model *can* do, only how it renders.

| Knob | Default | What it does / how to push it |
|---|---|---|
| `scheduler` | `EULER_ANCESTRAL_DISCRETE` | The sampler. Euler-Ancestral gives sharper detail than the model's old DDIM default. Other valid values: `EULER_DISCRETE` (more stable/deterministic), `DDIM`, `LMS_DISCRETE`, `PNDM`, `AUTO` (= the model's own). An unknown value safely falls back to the model default. |
| `guidance_scale` | `7.0` | How literally it obeys the prompt. **Sweet spot 5–8.** Lower (\~4–5) = more natural, photoreal; higher (\~8–9) = more literal adherence but can look over-saturated / "fried." Range 0–30. |
| `steps` | `30` | Denoising steps. **Useful range \~25–40.** This is NOT a few-step model — very low values (e.g. 6) produce **pure noise**. More steps = slightly more detail, slower. |
| `negative_prompt` | (quality terms) | Steers *away* from the common artifacts (bad hands, blur, watermarks, bad anatomy). It is **quality-only** — it contains **no content/subject terms**, so it does **not** re-censor the model. Edit it freely; set to `""` to disable. A per-`/imagine` negative would override it. |
| `hires_enabled` | **`false`** | The hires-fix second pass (§6). **Off by default since 2026-07-02** — at the shipped `hires_max_edge`/`hires_factor` it exhausts system RAM on this box (§6). Turning it on is opting into that risk; read §6 first. |
| `hires_factor` | `1.5` | Upscale multiple for the refine pass (1.0–4.0). Lower to `1.25` if you hit the memory fallback (§6). |
| `hires_strength` | `0.4` | How much the refine pass changes the image (low = preserve composition, just add detail). |
| `hires_max_edge` | `1536` | Hard cap on the refined image's longest edge — a memory safety limit. |

---

## 6. Performance & memory bounds (why an image sometimes comes out "plain")

- **Resolution:** 1024×1024 is the native and best size; it is capped there.
  Going higher risks duplicated/garbled features and a lot more memory.
- **Time:** measured live in-app `/imagine` turns run **\~50–60 s** for a base
  image (50.7 / 56.0 / 58.6 s); cold end-to-end runs recorded 43.8 s photoreal,
  39.8 s illustration, 60.6 s cartoon. **Budget about a minute** — no end-to-end
  turn on record matches the "30 s" this guide used to claim. (The *generate step
  alone* is faster — a 20-step run measured \~30 s — but you never see it in
  isolation: SDXL is evicted after every image, so each `/imagine` reloads the
  pipeline, then generates, then stores the encrypted result.)
  Hires-fix is **off by default**
  (see below); when it was on it roughly doubled that, and in the measured failure
  case took \~209 s.
- **The memory ceiling is real, and base generation runs close to it.** The
  machine has a **31.3 GiB** ceiling shared between the CPU and the GPU. (All the
  figures in this bullet are GiB, so they can be compared against each other and
  the ceiling.) Evicting the always-loaded 14B frees roughly **8 GiB** when it was
  freshly built; after it has been reloaded during a session an evict returns
  \~11 GiB, but the extra is transient state the reload path allocates, not the
  model itself, and it is all returned. So the resident 14B is about **8 GiB of the
  budget**. The recorded phase-0 gate for a base 1024² generate **with the 14B held
  resident** peaked at **26.0 GiB, leaving 5.3 GiB headroom**. A later live session
  measured a tighter peak still: **\~29.1 GiB in use with only \~2.1–2.6 GiB
  available** during `/imagine`. Treat base generation as fitting, but not
  comfortably.
- **Hires-fix is OFF by default, and that is a deliberate safety decision.**
  `hires_enabled = false` since 2026-07-02, set after an operator live-verify on
  this exact box. What was measured: the 1536² refine drove system RAM to **100%
  (8 MB available)** *even with the 14B evicted* — so the earlier idea that
  evicting the 14B would let hires run cleanly co-resident was tested and did not
  hold. That generate took **\~209 s** (past the 175 s UI failsafe, producing a
  false "timed out" while the image had in fact been made), and it left the
  process degraded: the next `/save` reported "Insufficient memory" with 22 GB
  actually free. Base 1024² is fast and stable by comparison — but as the bullet
  above records, it is not running with lots of room to spare, which is exactly
  why the extra buffers of a 1536² refine had nowhere to go.
- **If you want to re-enable it**, do not just flip `hires_enabled`. Lower the
  ceiling first — `hires_max_edge = 1280`, `hires_factor = 1.25` — and re-measure
  RAM headroom. The shipped `1536` / `1.5` values are the ones that failed.
- **Hires-fix is fail-soft when it does run.** If the refine pass runs out of
  memory it **silently returns the base (un-refined) image** rather than failing
  the whole generation. So if an image unexpectedly comes out at plain/base
  quality, that is why — in `launcher.log` you will see a `hires-fix refine` line
  followed by a fall-back.
- **Timeout:** a very long generation can exceed the app's wait window and show a
  "timed out" message even though the image was generated and stored. With hires
  off, base generations sit well inside the window.

---

## 7. Quick recipes

- **A person who should look good:** frame them close (portrait/medium shot), keep
  the prompt under \~50 words, `guidance_scale` \~6.
- **A multi-subject scene:** describe each subject concretely, place them "in the
  foreground," and accept you may need 2–3 re-rolls.
- **Restyle an image you like:** `/edit blarai-img://<id> <new lighting / color /
  mood>` — don't ask it to add or move things.
- **It ignored part of the prompt:** shorten the prompt, front-load the missing
  element, or raise `guidance_scale` to \~8.
- **It drew a cartoon character oddly:** remove the character's name; describe the
  appearance and pose instead.
- **It came out as noise:** check `steps` is \~30, not a tiny number.

---

## 8. Safety boundary

The model is **uncensored for legal content** — that legal boundary is the
operator's sole, documented responsibility (a deliberate accepted-risk, ADR-033
§content-safety). The negative prompt is a *quality* steer and does **not** filter
content. Content safety here is governance plus the one-time go-live attestation,
not an automatic classifier.
