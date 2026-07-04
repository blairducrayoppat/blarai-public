# UC-010 Dispatch Asset Pipeline — generation for headless dispatch builds

**Status (Phase 3, 2026-06-30):** SHIPPED via **SEAM A** — the dispatch generates image assets
through the **in-runtime `image_gen.py`** path (the same governed generator `/imagine` uses),
AO-side, while the 14B is resident, BEFORE the model swap (`feat/uc010-dispatch-asset-gen`, #714;
dormant behind `BLARAI_ENABLE_ASSET_GENERATION`). This **supersedes the Phase-2b design recorded
below**, which sketched a *separate* build-time tool (`asset_gen.py`, Playground v2.5). The Phase-2b
record is kept for its measured findings.

## Phase 3 — SEAM A (the shipped design; supersedes Phase 2b)

**Why SEAM A, not the Phase-2b "ASSETS swap phase":** the only measured memory constraint is
*image-model + 30B* (32.5 GB > the 31.323 GB ceiling). Base SDXL + the **14B** co-reside fine
(~26 GB, 5.3 GB headroom — ADR-033 §Memory Phase-0; it is exactly how `/imagine` runs today). So the
dispatch generates AO-side at approve time WHILE THE 14B IS RESIDENT and BEFORE the swap, commits the
PNGs into the target repo baseline (every best-of-N coder candidate inherits them), then the normal
14B→30B swap runs the coder against assets already in the tree. This avoids loading a diffusion model
in the detached swap driver (where the AO/14B is already torn down) entirely. The reserve "SEAM B" (a
driver-side `PHASE_ASSETS` that unloads before the 30B loads) is documented but only needed for a
*hires* asset that would evict the 14B — not used for base-resolution app graphics.

**Generator = the in-runtime `image_gen.py`**, not `asset_gen.py`. One maintained, governed generator
(the base-SDXL `illustration`/`cartoon` variants, #703). The dispatch call **skips the born-encrypted
`generated_images` store**, writing **plain PNG build artifacts** into `<repo>/assets/` (web:
`public/assets/`). Governance: these are **build artifacts, not the operator's `/imagine` gallery
content** — prompt-controlled (the operator's goal), inheriting the existing UC-010 attested posture,
no new classifier, no second crypto path (**ADR-033 Amendment 3**). The offline mandate is untouched —
a committed local file is not egress.

**`asset_gen.py` is RETIRED for the dispatch.** The Phase-2b standalone tool targeted Playground v2.5,
which was **abandoned (#703 — "coherent ≠ conditioned"; deleted)**. It is NOT on the dispatch path and
is **not modified here** — it sits in the `blarai-build` build area (which, note, is inside an
uncommitted home-directory git tree; left untouched). Its `rembg` transparent-cutout step remains an
**optional future follow-up** (nice for sprites/logos on arbitrary backgrounds), not a blocker for the
raster-into-`<img>` web case.

---

## What this is (Phase 2b — historical; the design SEAM A replaced)

The headless-coding dispatch (#670) builds apps but cannot *invent* design — it shipped a 🚀-emoji
"rocket calculator." Phase 2 gives it real illustration assets. This document covers **Phase 2b**:
the build-time pipeline that turns a prompt into a clean, embeddable app asset.

```
prompt → Playground v2.5 (OpenVINO INT8) → flat illustration → rembg cutout → clean subject on transparent PNG
```

Playground v2.5 draws good flat *subjects* but fills empty space with busy mosaic/dot clutter (a
known SDXL "hates empty space" trait). The LA's chosen fix (2026-06-24) is **background removal
first** — `rembg` isolates the subject onto a transparent background, which is the asset shape an
embedded app graphic needs anyway. A flat-vector LoRA stays a later option if more flatness is
wanted; it was not built.

## Governance posture (LA-CONFIRMED 2026-06-24) — a deliberate decision, not a side effect

> **Superseded by Phase 3 (SEAM A, 2026-06-30):** the dispatch now generates via the governed
> `image_gen.py` path and writes plain artifacts OUTSIDE the encrypted gallery — the same *net*
> posture (build artifacts, prompt-controlled, not gallery content; ADR-033 Am.3), reached through
> the one maintained generator rather than a second build-time tool. The framing below is the
> Phase-2b design, kept for the record.

Dispatch asset generation is a **build-time fleet tool** that writes plain PNGs into the app's
build tree. It is **outside** the governed UC-010 runtime capability:

- It does **not** go through the born-encrypted `generated_images` store.
- It does **not** require the UC-010 go-live ceremony / content attestation.
- Its content-safety rests on the **operator's prompt control**, the LA's accepted posture for
  dev / legal-content app assets — *not* the UC-010 attestation.

The user-facing UC-010 illustration variant (Phase 2a, `image_gen.py`) keeps full ADR-033
governance and is a separate path. Keeping the two separate keeps the governance boundary clean.

## The tool

`C:\Users\mrbla\blarai-build\img-convert\asset_gen.py` — a parameterized CLI:

```
python asset_gen.py --model <playground_dir> --outdir <dir> \
    --prompt "rocket_icon=<flat-vector prompt>" \
    --prompt "calc_hero=<flat-vector prompt>" \
    [--device CPU] [--size 768] [--steps 28] [--guidance 3.0] [--seed N] [--no-cutout]
```

Each prompt yields `<name>_raw.png` (the generation), `<name>_cutout.png` (RGBA, transparent
background), and `<name>_on_white.png` (cutout composited on white — what an app on a light surface
shows). It reuses the proven `optimum.intel.OVStableDiffusionXLPipeline` call shape (mirroring the
existing `smoke.py`/`brochure2.py`) plus a flat-vector quality/style negative prompt (NO content
terms — the model stays uncensored). The rembg step uses a `u2net` session by default
(`--cutout-model isnet-general-use` is an alternative for flat art).

**Isolation:** runs ONLY in the throwaway 3.11 conversion venv
(`blarai-build/img-convert/venv311`, Python 3.11.9 — `optimum-intel`/`diffusers`/`torch`/`rembg`),
NEVER BlarAI's runtime `.venv` (per the build-toolchain-isolation rule). `pip check` is clean after
the `rembg[cpu]` add; numpy stayed 2.4.6 and the OV pipeline + rembg coexist in one process.

## CPU vs GPU (a constraint, not a preference)

The standalone tool/proof runs on **CPU**. The Arc 140V GPU co-resides with the dispatch's resident
30B coder (OVMS), and a Playground + 30B co-residence was measured at a **32.5 GB ceiling breach**
(over the 31.323 GB limit). The standing rule also forbids stopping OVMS without an explicit task.
So the GPU asset path runs only inside the **Phase-3 model-swap sequence** (the 30B is swapped out
first). CPU generation is slower (see below) but proves the pipeline without GPU/OVMS contention.

## Validation (2026-06-24/25, Arc 140V host, CPU)

- **Model load:** ~9 s on CPU.
- **Generation:** 512²/20 steps ≈ 141 s; 768²/28 steps ≈ 475–485 s (~8 min) on CPU.
- **Cutout (rembg u2net):** < 1 s/image.
- **Cutout quality:** the busy mosaic/dot background is **removed cleanly**; the flat subject is
  isolated on transparent (~64% transparent for a centered single subject). Confirmed by viewing
  the images. The remaining artifacts (occasional duplicate subject, low-res noise, garbled
  pseudo-text) are **generation** quality, not cutout quality.
- **Generation tuning is the lever (the key finding).** The cutout only works when the generation
  yields a *distinct* subject. Two failure modes seen while tuning: (a) over-emphasising "empty
  white space / corporate icon" pales the whole image into a faint ghost (rembg then keeps faint
  near-white regions — useless); (b) under-constraining lets the SDXL mosaic clutter fill the entire
  frame (rembg finds no background to remove — ~2% transparent). The sweet spot is a bold, saturated,
  outlined subject ("sticker style, thick outline, bold solid colours") against a plain background —
  exactly what rembg isolates well. Prompt iteration is slow on CPU (~8 min/image) and belongs on
  the GPU (the Phase-3 swap-sequence path).

**Conclusion:** the gen → rembg → clean-cutout pipeline is proven. rembg is the right first move for
turning Playground's good-subject/bad-background output into usable isolated app assets; the open
work is generation prompt/setting tuning, which iterates fast only on the GPU (Phase 3).

## Phase 3 — DONE (see the top: SEAM A). Remaining optional follow-ups

Phase 3 shipped as **SEAM A** (generate AO-side pre-swap via `image_gen.py`), which is simpler and
more memory-safe than the "ASSETS swap phase" originally sketched here — that reserve path ("SEAM B",
a driver-side `PHASE_ASSETS` that unloads the image model before the 30B loads) is documented but only
needed for a hires asset that evicts the 14B. Optional follow-ups (none blocking):
- `rembg` transparent-cutout, imported into the SEAM-A generate for sprite/logo assets on arbitrary
  backgrounds; evaluate `isnet-general-use` vs `u2net` for flat-art edges.
- Wider aspect ratios than the base 1024² square (kept square for the proven co-resident envelope).
- A flat-vector LoRA if more style flatness is wanted (the `/cartoon` runtime LoRA already softens).
