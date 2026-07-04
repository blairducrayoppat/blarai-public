# ADR-015: Local Vision — Qwen3-VL-8B via VLMPipeline (store-only seam)

**Status:** Accepted — LA-directed 2026-06-03; MVP live-verified in BlarAI.
**AMENDED 2026-06-04** (LA-directed, Vikunja #561): the **injection point moved
from Option A (eager, attach-time, generic) to a context-aware on-demand design
("brain directs the eyes")** — see the *Amendment* section at the foot of this
file. The original decision is kept intact above it as the record of the path
first taken.
**Builds on:** ADR-014 (WinUI store-only photo/video seam) + BUILD_JOURNAL lesson #12
(build the envelope before the capability). **Tracked:** Vikunja #550, #561.

## Context

The WinUI surface was deliberately built **vision-ready**: photo/video attachments
are first-class (file picker, drag-drop, inline chips, screenshot capture), stored
in `userdata/`, and grounded with a placeholder ("BlarAI cannot interpret images
yet"). Only the grounded text was meant to change when a vision model landed.

The User-Operator wants image understanding now — initially to help a landscape
business (describe property photos, identify plants/features, draft sales text).

## Decision

Wire **`OpenVINO/Qwen3-VL-8B-Instruct-int4-ov`** via `openvino_genai.VLMPipeline`
on the GPU. (It is the *only* INT4 OpenVINO-org Qwen3-VL — 4B/2B int4-ov repos do
not exist.)

- **Injection point (Option A):** `document_loader.load_document()` — for images,
  generate a rich description **at attach-time** and return it as the grounded
  `content`; the 14B then answers the user's question against that description.
  (Simpler than per-question VLM calls; the description is question-agnostic.)
- **Fail-Soft:** `shared/inference/vlm.py` returns `None` on any failure (model
  missing, GPU OOM, decode error) → the loader falls back to the placeholder, so
  vision can never break the app.
- **Lazy-load + cache:** the VLMPipeline loads on first image and is cached.

**Scope (MVP, this session):** image *understanding* — describe, recognize
plants/features, answer questions, draft text. Hardware-validated: VLM loads on
the Arc 140V in \~13 s, describes in \~16 s (PERFORMANCE_LOG 2026-06-03); live-verified
on a real photo.

**Explicitly NOT in scope (honest limits):**
- **Precise 3D measurement** — VLMs *guess* at metrics; the description prompt
  forbids estimating dimensions. Real measurement is **photogrammetry** (multi-view
  reconstruction / LiDAR), a separate pipeline needing capture changes — future track.
- **Rendering generation** — that is image *generation* (a diffusion model, e.g.
  Text2ImagePipeline), a separate model entirely — future track.
- **Video** (images only this round); **per-question VLM answering** (Option B).

## The open hard problem (memory)

The VLM (\~5 GB) loads on the GPU **alongside the resident 14B** (\~8.7 GB) + Whisper
+ embedder, against the **31.3 GB shared ceiling**. Co-resident cost is **UNMEASURED**
(PERFORMANCE_LOG flags it as the key trend gap). Mitigations: Fail-Soft degrades an
OOM to the placeholder; **load-on-demand 14B eviction** is the planned next iteration
if co-residency proves unstable in live use.

## Consequences

- **+** Image understanding shipped behind the existing seam; zero UI rewrite (lesson #12 paid off).
- **−** Co-residency unmeasured (brick risk bounded by Fail-Soft).
- **−** HEIC/HEIF can be *attached* but need `pillow-heif` to decode (else Fail-Soft placeholder).
- **−** First-image latency \~30 s (VLM load + describe); cached after.

## Landscape use-case roadmap (honest feasibility, per the LA discussion)

1. **Understanding** (now) — describe/recognize/answer/draft. ✅
2. **Plant-species precision** — VLM is first-pass only; a specialized model (PlantNet-class) for authoritative species. ⚠️
3. **Photogrammetry measurement** — multi-view 3D reconstruction; needs capture changes (overlap + scale reference / LiDAR); BlarAI could orchestrate it. 🔜 separate pipeline
4. **Rendering generation** — diffusion model (image-gen); her existing rendering software is likely better than local generation. 🔜 separate model
5. **Data-export to her rendering software** — feasible once the software's import format is known; BlarAI emits structured findings. 🔜 gated on the target format

## Implementation

`shared/inference/vlm.py` (VLMPipeline wrapper, lazy + cached + Fail-Soft) ·
`document_loader.load_document()` image branch (VLM call + placeholder fallback) ·
attach-filter broadened (16 → 64 MB cap; + `.jfif/.bmp/.tif/.tiff/.heif`). Tests
stub the VLM (`test_document_loader_media.py`) so the suite never loads the 8B model.

---

## Amendment — 2026-06-04: "brain directs the eyes" (on-demand, context-aware)

**Status:** Accepted — LA-directed. **Tracked:** Vikunja #561. **Supersedes** the
*Decision* section's **Option A** (eager attach-time grounding) above.

### Why the original injection point had to change

Option A described every image **eagerly on attach, generically, on the event
loop**, and the first Tier-0 live boot showed all three were wrong:

- **It ignored intent.** A 256-token landscaping-oriented description was written
  *before the user asked anything* — useless for "is this rash infected?" and
  wasteful for everything that is not a garden.
- **It froze the app.** The grounding ran synchronously on the backend's single
  event loop, monopolising the only serialised lane; a voice clip captured at
  22:10:39 was not handed to the transcriber until 22:15:27 — a \~5-minute queue
  behind one photo (BUILD_JOURNAL lessons 24, 25).

### The amended decision (Option B+, the hybrid the LA chose)

1. **Attach is lazy.** `document_loader` reads no pixels and runs no VLM on
   attach; it stashes the resolved `image_path` and a `pending_vision` flag and
   returns instantly with a "staged — analyzed when you ask" message. The UI
   thumbnail shows immediately.
2. **The brain formulates the query.** When the user prompts about a staged
   image, the 14B writes a **context-aware vision query** from the conversation +
   the message (e.g. "report colour, texture, borders, distribution, scaling" for
   a suspected rash). This is **skipped** for a bare deictic question
   ("what's this?") — the question goes straight to the eyes (speed).
3. **The eyes answer.** `describe_image(image_path, prompt=query)` runs the VLM
   on demand. Fail-Soft unchanged: `None` → a factual "could not analyze this
   turn" note, never a crash.
4. **The answer folds back as DATA.** The VLM output is grounded via
   `context_manager.add_grounded_context(...)`, so it is wrapped in Context
   Spotlighting delimiters and **datamarked** — read as data, never obeyed as
   instruction (lesson 13, provenance ≠ trust). A vision model captioning an
   attacker's photo cannot inject the assistant.

### Where it runs (topology) and the coupling that follows

The formulate → VL → ground sequence runs **AO-side**, because in the default
**host** deployment the AO is a native process with direct filesystem + GPU
access — it runs both the 14B (formulation) and the VLM in-process. The gateway
therefore ships only a lightweight **path** + flag over vsock, not image bytes
(images reach 64 MB; the PROMPT_REQUEST frame caps at 64 KB), and no AO→gateway
callback is needed (none exists). **Coupling recorded for the future:** this
assumes host-mode filesystem access and a path small enough for vsock; **guest
mode** (AO in the VM) has neither and must solve image delivery differently —
captured as a constraint in **ADR-022** + the VM-isolation hardening ticket.

### Freeze fix (independent, shipped first)

The dispatcher's `_m_load_document` / `_m_store_attachment` were moved off the
event loop (`asyncio.to_thread`) so no document work — vision or otherwise — can
ever seize the loop again (lesson 25). This is behaviour-preserving and landed as
its own commit ahead of the lazy/context-aware change.

### Deferred (not this pass)

- **VM-isolation of untrusted image handling** (decode + VLM) → **ADR-022** +
  hardening ticket, tied to the network-facing-future track. The honest framing:
  on this silicon it is CPU-side sandboxing of a decoder exploit, **not** a
  confidential-GPU boundary (no TDX Connect/TDISP — Phase 2 Gate 4), at a
  performance cost; a cheaper *decode-in-a-sandbox* middle path is recorded there.
- **Co-residency memory pressure** (VLM \~5 GB + 14B \~8.7 GB) is unchanged by this
  amendment — a single-GPU fact independent of where the process runs — and stays
  on the #550 / load-on-demand-eviction track.

### Implementation (amendment)

`document_loader.load_document()` image branch (lazy stash: `image_path` +
`pending_vision`, empty `content`) · `entrypoint._ground_pending_image` /
`_formulate_vision_query` / `_is_bare_visual_question` (AO-side formulate → VL →
datamarked ground) · `dispatcher` document methods off-loop · framer `documents`
carries the image fields verbatim. Tests: `test_document_loader_media.py`
(lazy + attach-does-not-call-VLM), `test_entrypoint_document_wiring.py`
(`TestAOLazyImageGrounding`: formulate→VL→ground, bare-question skip, datamarking,
Fail-Soft), `test_dispatcher.py` (off-loop thread-identity).
