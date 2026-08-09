# Model Evaluation — Gemma 4 12B as an Upgrade/Replacement Candidate

**Type:** Research & decision-support report (NO implementation). For Lead Architect review.
**Date:** 2026-06-06
**Author:** Copilot Agent (Claude Opus 4.8), at LA direction
**Status:** DECISION PENDING — this report does not change any architectural lock. It is
input for a roadmap go/no-go.
**Scope question (LA-sharpened):** Is **Gemma 4 12B** a *true* replacement for the
current model set — specifically for **Qwen3-VL** — once agentic ability, speculative
decoding, and the multimodal aspect are all weighed?

> **Addendum B (2026-06-06, second LA reframe) — READ THIS FIRST if you are evaluating
> consolidation.** The LA has explicitly set aside two of §1–§10's "blockers": (1) the
> Qwen3-specific **security-harness rebuild is accepted as normal upgrade work**, not a
> reason to stop; (2) **OpenVINO support is a ticket-to-Intel**, not a wall. With those
> removed, the real question becomes purely conceptual: **is Gemma 4 12B *truly superior*
> as a single-model consolidation target** — worth an Intel ticket + a new harness?
> **That analysis is in [§11–§14 below](#11-addendum-b--the-consolidation-question-la-reframe).**
> The original §0–§10 still stands as the "today, drop-in" view; §11+ is the "is it worth
> the effort" view the LA actually asked for.

> **Reading note.** This is intentionally long because the LA asked for enough
> information to make an informed decision, not a verdict to rubber-stamp. The
> executive summary is the TL;DR; §7 is the direct answer to the sharpened question;
> §9 is the recommendation with named alternatives. Everything between is the evidence.

---

## 0. Executive Summary

- **BlarAI is a model-defined system.** The local models are not a component of BlarAI —
  they *are* the product. Every capability (policy adjudication, conversation, vision,
  voice, the future code agent) is a thin deterministic harness around a locally-run
  model. Swapping the model is the highest-leverage and highest-blast-radius change the
  project can make.
- **There is not one model to replace — there are three live stacks.** (1) **Qwen3-14B**
  INT4 on GPU is the text workhorse (Policy Agent + Assistant Orchestrator + future
  Code Agent, shared pipeline). (2) **Qwen3-VL-8B-Instruct** INT4 on GPU is the vision
  model (`VLMPipeline`, hardware-validated 2026-06-03). (3) **Whisper-small + Kokoro-82M**
  is the voice stack. Plus BGE-small on CPU for the semantic router.
- **Gemma 4 12B is genuinely novel** — a *unified, encoder-free* multimodal model
  (text + image + **audio**) released **2026-06-03 (3 days ago)**. Its uniqueness is
  architectural, not just a bigger-number release (§5). On paper it could collapse
  **vision + voice-in** into a single model.
- **The decisive constraints are runtime, not quality:**
  1. **OpenVINO support for the *encoder-free 12B* is not demonstrated.** OpenVINO's
     "Gemma 4 functional preview" (2026.0/2026.1) was published in **April 2026**, predates
     the 12B, and explicitly enumerates the **encoder-based** family (E2B/E4B/26B-A4B/31B).
     It is **CPU-first**; GPU is **nightly/preview only**. BlarAI mandates **GPU** (ADR-011).
  2. **Gemma 4's speculative decoding is MTP**, and MTP today is a **vLLM/CUDA** path
     (needs `transformers 5.8.0.dev0` + a specific vLLM PR). There is **no OpenVINO GenAI
     MTP path**. BlarAI's spec-decode is **mandatory** (ADR-012) and uses OpenVINO's
     draft-model API. This is a throughput-critical gap.
  3. **The headline benchmark numbers belong to the 31B / 26B-A4B**, *not* the 12B. The
     12B is positioned between E4B (8B) and 26B-A4B; Google's own claim is "near 26B-MoE
     quality at <half the memory." Strong — but do not import flagship scores onto it.
- **Bottom line:** Gemma 4 12B is a **compelling WATCH**, not a **now-swap**. As a
  *Qwen3-VL replacement* it is architecturally attractive (and uniquely adds audio), but
  **today it is blocked on the exact runtime path BlarAI is locked to** (OpenVINO + Arc
  GPU + mandatory spec-decode). As a *Qwen3-14B text replacement* it would also dynamite a
  large amount of locked, hard-won Qwen3-specific engineering (thinking-mode suppression,
  token-ID stop logic, DPC) for no capability the text role currently lacks.
- **This is a DECISION for the LA, not a defect to fix** — it changes capability, quality,
  and security posture. Named alternatives in §9.

---

## 1. How BlarAI's AI System Works (and why the model is the system)

BlarAI's Priority-1 Core Loop is two operational use cases wrapped around local models:

| Stage | Component | Model | Device | Role |
|-------|-----------|-------|--------|------|
| M1 | Semantic Router | BAAI/bge-small-en-v1.5 (33M) | CPU | Embedding/intent routing, sub-80 ms |
| M2 | **Policy Agent (USE-CASE-001)** | **Qwen3-14B INT4** | **GPU** | Content classification (ALLOW/DENY/ESCALATE), fail-closed |
| M3 | **Assistant Orchestrator (USE-CASE-004)** | **Qwen3-14B INT4** | **GPU** | Conversational generation |
| (vision) | VLM seam (ADR-015) | **Qwen3-VL-8B-Instruct INT4** | **GPU** | Image understanding, lazy-load, Fail-Soft |
| (voice) | Voice engine (ADR-017) | Whisper-small (STT) + Kokoro-82M (TTS) | CPU/GPU | Speech in/out, fail-soft |
| (future) | Code Agent (USE-CASE-005) | Qwen3-14B INT4 | GPU | Coding agent inside BlarAI runtime |

Key architectural facts that make the model choice load-bearing:

- **Shared pipeline.** PA and AO are the *same* compiled `ov_genai.LLMPipeline`
  (single compilation, shared weights, serialized by a lock) — ADR-012 §2.1/§3.1. A model
  swap is a swap for *both* the classifier and the conversationalist at once.
- **Determinism mandate.** `do_sample=False`, `temperature=0`. The classifier's behavior is
  a security control, not a UX preference.
- **The harness is Qwen3-shaped.** The thinking-mode strategy (PA `/no_think`, AO thinking +
  block strip), the stop-token logic (`<|im_end|>`=151645, `<think>`=151667, `</think>`=151668),
  and the DPC (deterministic-prefilter classifier) are all **locked, empirically-tuned to
  Qwen3's exact tokenizer and chat template** (ADR-012 §2.4; the entire
  `LESSONS_LEARNED_QWEN3_THINKING_SUPPRESSION.md`). This is not portable to another model
  family for free.

**Implication:** the models carry the product. The harness around them is deliberately thin
and deterministic — which is good engineering, but it also means the model's exact
behavior, tokenizer, and runtime support are baked into dozens of locked decisions.

---

## 2. Technical Constraints (the box every model must fit in)

| Constraint | Value | Source | Why it bites a model swap |
|------------|-------|--------|---------------------------|
| Effective memory ceiling | **31.323 GB** | ADR-005 | Hard wall; GPU shares LPDDR5X with everything |
| GPU agent-tier budget | **~15,507 MB** | ADR-006 | All co-resident model weights + KV caches live here |
| Device mandate | **All LLM inference on Arc 140V GPU; NPU retired** | ADR-010/011 | A model is only viable if it runs *well on Arc via OpenVINO* |
| Runtime | **OpenVINO GenAI** (`LLMPipeline`/`VLMPipeline`) | ADR-012/015 | Support must exist for the *exact* model+precision+device |
| Precision | **INT4 symmetric (gs=128)**; **FP16 KV**; **BF16 unsupported on Arc** | ADR-012 §2.2 | Arc 140V accepts only f16/f32/dynamic compute |
| Speculative decoding | **Mandatory** (draft model, OpenVINO draft API) | ADR-012 | Without it, 14B-class TPS on Arc is unacceptable |
| Context window | 16,384 locked (20,480 proven safe) | ADR-012 §2.2 | Spec-decode goes inert >~12K (AR→0) |
| Privacy | **Absolute, fail-closed, zero network** | CLAUDE.md | Model + runtime must work fully offline/local |
| Determinism | temperature=0 equivalent | project mandate | Classifier behavior is a control surface |

The throughput baseline the incumbent already achieves (Qwen3-14B INT4 + draft, Arc 140V):
**4K ctx → 10.72 tps · 8K → 7.74 · 16K → 4.94** (ADR-012 §2.2). Any replacement must clear a
comparable bar *on this hardware and runtime*, not on an H100/RTX with vLLM.

---

## 3. The Resource-Pressure Stack (what individually adds up to BlarAI's footprint)

BlarAI's pressure on the host is the **sum of independent tiers** (ADR-006 tier summation),
all bounded by the 31.323 GB ceiling. Breaking it into the elements the LA asked about:

| Pressure element | Footprint | Notes |
|------------------|-----------|-------|
| **Host OS baseline** | ~13 GB (prod) / ~18 GB (dev) | Dev inflated by VS Code/Firefox/Word (~5 GB removable) |
| **Hypervisor (Hyper-V root)** | ~512 MB | Root partition reservation |
| **Orchestrator VM (Alpine)** | 2 GB fixed | Gen-2 VM, no network, vsock only |
| **Qwen3-14B INT4 weights (resident)** | ~9.1 GB on-disk `.bin`; ~8.7 GB VRAM | The always-on text model |
| **Draft model (resident)** | ~300–367 MB | Qwen3-0.6B INT4 → pruned-6L INT8; required for spec-decode |
| **14B KV cache (FP16)** | grows with context | Peak total RSS measured **~12.0–12.5 GB** across configs |
| **Qwen3-VL-8B (on-demand)** | **~5 GB** | Loads **alongside** the 14B on first image; co-residency **UNMEASURED** (ADR-015 "open hard problem") |
| **Whisper-small + Kokoro-82M** | hundreds of MB each | Voice in/out, fail-soft, optional |
| **Semantic router (BGE-small)** | ~33–66 MB | CPU, INT8 OV |
| **Substrate store / SQLite sessions** | small, AES-256-GCM at rest | ~0.1 ms/query crypto overhead (PERFORMANCE_LOG 2026-06-06) |

**The single most important pressure fact for this decision:** the GPU tier is already
near its limit when vision co-resides with text. The VLM (~5 GB) + 14B (~8.7 GB) ≈ **13.7 GB**
against the **~15.5 GB** budget, *before* KV growth — which is exactly why ADR-015 flags
co-residency as unmeasured and names "load-on-demand 14B eviction" as the fallback. **Any
replacement model's memory profile must be read against this already-tight envelope**, not
against the raw 31 GB.

---

## 4. The Incumbents — Profiles

### 4.1 Qwen3-14B (the text workhorse)

| Property | Value |
|----------|-------|
| Params | 14.8B (13.2B non-embedding), 40 layers, hidden 5120 |
| Attention | GQA — 40 Q heads / 8 KV heads |
| Vocab | 151,936 |
| Context | 32,768 native; 131,072 via YaRN |
| Modality | **Text only** |
| Thinking mode | Native `/think` ↔ `/no_think` toggle (load-bearing in BlarAI) |
| Agentic | Strong tool-calling (Qwen-Agent, MCP templates) |
| Licence | Apache-2.0 |
| BlarAI deployment | INT4 sym, GPU, shared PA+AO pipeline, mandatory draft spec-decode |
| Runtime status | **First-class OpenVINO GenAI supported** (`Qwen3ForCausalLM`, listed incl. 14B) |

### 4.2 Qwen3-VL (the vision line; BlarAI runs the 8B-Instruct)

| Property | Value |
|----------|-------|
| Family | Dense + MoE, 2B/4B/8B/32B/30B-A3B/235B-A22B; Instruct + Thinking editions |
| Architecture | Encoder-based ViT with **DeepStack** (multi-level ViT fusion) + **Interleaved-MRoPE** |
| Context | Native **256K**, expandable to **1M** |
| Modality | Text + image + **video**; strong OCR (32 languages), spatial/3D grounding, visual agent (GUI control) |
| BlarAI deployment | `OpenVINO/Qwen3-VL-8B-Instruct-int4-ov` via `VLMPipeline`, GPU, lazy-load + cached + Fail-Soft |
| Validation | **Hardware-validated 2026-06-03**: loads ~13 s, describes ~16 s on Arc 140V |
| Role in BlarAI | "Brain directs the eyes" — the 14B formulates a context-aware query, the VLM answers, output folds back as *datamarked* grounding (never obeyed) |

**Why this matters for the comparison:** Qwen3-VL is not a paper candidate — it is **already
on disk, already OpenVINO-INT4, already wired behind a hardened seam, already proven on the
exact GPU.** That is a very high bar for a 3-day-old model to clear.

---

## 5. Gemma 4 12B — Profile and Why It Is Unique

Released **2026-06-03**. The uniqueness is real and worth stating precisely, because it is the
crux of the "true replacement" question.

### 5.1 What makes it unique: the *encoder-free, unified* architecture

Every other multimodal model in this class — **including Qwen3-VL and the other Gemma 4
sizes** — uses **separate, frozen encoders** to turn images (and audio) into tokens before
the LLM sees them: a ViT vision encoder (Qwen3-VL's DeepStack; Gemma 4 31B's 550M-param ViT)
and, for audio, a conformer encoder. Gemma 4 12B **removes them**:

- **Vision:** raw **48×48 pixel patches** are projected straight into the 3,840-dim decoder
  space with a *single matmul* (~35M-param embedder, most of which is just the pixel→hidden
  projection). Spatial position is injected via two **X/Y coordinate lookup matrices** instead
  of a ViT's 2D-RoPE.
- **Audio:** raw 16 kHz waveform is sliced into **40 ms / 640-float frames** and linearly
  projected — no conformer encoder at all.
- **Consequence:** all modalities share the *exact same weights*; the decoder does the
  perceptual work it used to offload to encoders. Multimodal tokens reach the LLM **faster**
  (no encoder pre-pass → lower latency), the memory footprint is unified, and fine-tuning
  updates the whole multimodal loop in one pass.

Other notable Gemma 4 12B traits (from Google's guide + the visual guide + ecosystem):
- Same decoder structure as the **Gemma 4 31B Dense** (interleaved local/global attention,
  global last); hidden size **3,840**.
- **Audio in a medium model** — Gemma 4 12B is the **first medium-sized Gemma to natively
  ingest audio** (the bigger 26B-A4B/31B do image+video but **not** audio; audio otherwise
  lived only in the tiny E2B/E4B). This is the single most strategically interesting fact
  for BlarAI's voice ambitions.
- **Thinking mode** (`enable_thinking=True`), **native function calling** (JSON tool calls
  without special prompting), **Per-Layer Embeddings (PLE)**, **shared KV cache** in late
  layers, **Apache-2.0**.
- **Speculative decoding via MTP** (Multi-Token Prediction): ships a **separate assistant
  checkpoint** (`gemma-4-12B-it-assistant`) rather than a generic draft model.
- **Sizing:** Google targets **16 GB VRAM / unified memory**; claims the 12B "delivers
  performance nearing our larger 26B MoE model… at less than half the total memory footprint."

### 5.2 Benchmarks — read with care

The widely-quoted Gemma 4 leap (AIME 2026 **89.2%**, LiveCodeBench v6 **80.0%**, GPQA Diamond
**84.3%**, Codeforces ELO **2150**, MMMU-Pro **76.9%**, MRCR-128K **66.4%**) is for the **31B**
(and the 26B-A4B close behind). **These are not the 12B's numbers.** The 12B sits below them by
design. The honest, attributable statement for the 12B is Google's own: **near-26B-MoE quality
at <half the memory.** Treat anything more specific as unverified until the 12B is benchmarked
on BlarAI's hardware.

---

## 6. Agentic, Speculative Decoding, Multimodal — head to head

### 6.1 Agentic ability

| | Qwen3-14B / Qwen3-VL | Gemma 4 12B |
|---|---|---|
| Tool calling | Strong; Qwen-Agent + MCP templates; mature ecosystem | **Native function calling** (clean JSON), thinking-mode + tool reasoning |
| Visual agent | Qwen3-VL: GUI control, grounding, computer-use cookbooks | Agentic + multimodal demos (OpenCode harness, builds local apps) |
| Maturity on BlarAI's stack | Proven in-product | Unproven on OpenVINO/Arc |

**Read:** both are credible agentic models. Gemma 4's native function calling is a genuine
strength and broadly at parity with Qwen3's tool-calling for BlarAI's purposes. Agentic
ability is **not** the deciding axis — it's close to a wash on capability, and Qwen wins only
on *proven integration*.

### 6.2 Speculative decoding (the throughput-critical axis)

This is where the two diverge in a way that matters enormously for BlarAI:

- **Qwen3 (incumbent):** BlarAI uses OpenVINO GenAI's **draft-model** speculative decoding
  (`draft_model=ov_genai.draft_model(...)`). Locked, tuned (NAT=3), and **mandatory** —
  it's the only reason the 14B hits acceptable tps on Arc. A small separate Qwen3 draft
  (0.6B / pruned-6L) predicts; the 14B verifies.
- **Gemma 4 12B:** speculative decoding is **MTP** (Multi-Token Prediction) via a dedicated
  **assistant checkpoint**. Critically, **MTP support today is a vLLM/CUDA story**: it needs
  `transformers 5.8.0.dev0` (to register `gemma4_assistant`) and a specific vLLM PR; older
  runtimes that treat the assistant as a generic draft model "**may fail during
  initialization for multimodal Gemma 4 targets.**" There is **no evidence of an OpenVINO
  GenAI MTP path** — OpenVINO's own Gemma 4 roadmap lists "GenAI with paged attention" as
  *coming*, with no MTP mention.

**Read:** on BlarAI's runtime (OpenVINO + Arc), the incumbent's spec-decode **works today**;
Gemma 4 12B's spec-decode **does not have a demonstrated path**. Since spec-decode is
mandatory for this model class on this hardware, this is a **gating risk**, not a footnote.
Without it, a 12B on Arc would likely run autoregressively at a fraction of usable tps.

### 6.3 Multimodal

| Axis | Qwen3-VL-8B (incumbent) | Gemma 4 12B |
|------|------------------------|-------------|
| Image understanding | Yes — strong OCR, grounding, video | Yes — strong vision benchmarks (flagship sizes), encoder-free |
| Audio **input** | No (BlarAI uses Whisper separately) | **Yes — native** (the unique win) |
| Video | Yes | Yes (per family; 12B per Google guide demo) |
| Encoder latency | Encoder pre-pass (ViT) | **None** — raw projection, lower first-token latency |
| Context | 256K→1M | 256K-class |
| On BlarAI today | INT4-OV, GPU, validated | OpenVINO path for encoder-free 12B **unproven** |

**Read:** Gemma 4 12B's multimodal *architecture* is arguably ahead — it natively unifies
audio + image + text, which Qwen3-VL does not (Qwen3-VL is vision/video, not audio-in). If it
ran on BlarAI's stack, it could **collapse Qwen3-VL + Whisper into one model**. That is the
genuinely exciting thesis. But "if it ran on BlarAI's stack" is the unproven part.

---

## 7. Direct Answer: Is Gemma 4 12B a *true* replacement for Qwen3-VL?

**Short answer: Not today, and not a clean one-for-one even later — but it is the most
interesting *future* vision/voice candidate the project has seen.**

Breaking "true replacement" into the parts that actually matter:

1. **As a vision model (the literal Qwen3-VL job): Architecturally yes, operationally no
   (today).**
   - *For it:* encoder-free image understanding, strong vision lineage, **and it adds native
     audio** — a superset of what Qwen3-VL gives BlarAI. It could replace the VLM seam *and*
     the Whisper STT half in one model. Memory target (16 GB) is in the same ballpark as the
     ~5 GB INT4 VLM once quantized.
   - *Against it:* the **encoder-free 12B has no demonstrated OpenVINO GPU path**. OpenVINO's
     Gemma 4 enablement (April 2026) is for the **encoder-based** family and is **CPU-first /
     GPU-nightly**. The 12B's raw-patch vision and raw-audio projection are **new input paths**
     that need fresh Optimum-Intel/OpenVINO enablement before `VLMPipeline`-style use on Arc
     is even possible. Qwen3-VL, by contrast, is already INT4-OV and hardware-validated.
   - *Verdict:* a **superior replacement on paper**, **blocked on runtime today.**

2. **As the text workhorse (Qwen3-14B's job): No, and not advisable purely on capability
   grounds.**
   - Replacing the 14B means re-engineering the **entire locked Qwen3-specific harness** —
     thinking-mode suppression, the exact stop-token IDs, the DPC prefilter, the PA quality
     gate (0.9483) — against a different tokenizer and chat template. That is a large,
     security-sensitive rebuild (the Policy Agent is a control surface) for **no text
     capability the 14B currently lacks**.
   - It also forfeits the **proven draft spec-decode** for the **unproven-on-OpenVINO MTP**.
   - *Verdict:* high cost, high risk, low marginal benefit for the text role specifically.

3. **As a *unifier* (one model for text + vision + voice-in): Tempting, premature.**
   - This is the dream the encoder-free design sells. But unifying onto Gemma 4 12B means
     accepting #1 and #2's risks simultaneously, on a 3-day-old model, on a preview runtime,
     losing mandatory spec-decode, and rebuilding the security harness. The **blast radius is
     the whole product.**

**So:** Gemma 4 12B is a *more capable multimodal model on paper* than Qwen3-VL (audio is the
clincher), but it is **not a true drop-in replacement** because (a) the runtime path BlarAI is
locked to does not yet support the encoder-free 12B on GPU, (b) its spec-decode is off-stack,
and (c) "replacement" for the text role would demolish a large amount of working, locked
engineering for no gain.

---

## 8. Risk / Cost Ledger (if a swap were attempted now)

| Risk | Severity | Notes |
|------|----------|-------|
| No OpenVINO GPU path for encoder-free 12B | **HIGH / likely blocking** | April-2026 enablement predates the 12B; GPU = nightly/preview; raw-patch+raw-audio need new enablement |
| MTP spec-decode absent on OpenVINO | **HIGH** | Mandatory spec-decode; MTP is vLLM/CUDA-only today |
| Security harness rebuild (PA) | **HIGH** | Thinking-suppression, stop-tokens, DPC are Qwen3-specific and security-load-bearing |
| Memory co-residency unproven | MED | Already tight at ~13.7/15.5 GB with current models |
| Benchmark misattribution | MED | Flagship scores are 31B/26B-A4B, not 12B |
| Model maturity (3 days old) | MED | Tooling churn (`transformers` dev builds, vLLM PRs), few converged INT4-OV artifacts |
| Determinism under thinking mode | MED | Thinking can emit 4,000+ tokens; latency/determinism budget impact (mirrors the Qwen3 PA lesson) |
| Loss of Qwen3-VL's 256K→1M ctx, OCR/grounding maturity | LOW-MED | Qwen3-VL is a very strong, proven VL model |

**What *reduces* risk over time:** OpenVINO explicitly promises **pre-converted IR, more GPU
support, and GenAI paged-attention** for Gemma 4. If those land **and** an encoder-free-12B
OpenVINO path with a working draft/MTP equivalent appears, items 1–2 could flip from blocking
to viable. That is the trigger to re-evaluate.

---

## 9. Recommendation (a DECISION for the LA, with named alternatives)

**Recommendation: Do NOT swap now. Adopt a WATCH posture and re-evaluate at a defined trigger.**
This is escalated as a *decision* (it changes capability, quality, and security posture), not
actioned as a defect.

Named alternatives, in increasing ambition:

- **(A) Status quo — Qwen3-14B (text) + Qwen3-VL-8B (vision) + Whisper/Kokoro (voice).**
  Lowest risk. Everything is proven, OpenVINO-INT4, GPU-validated, spec-decode working.
  *Cost:* forgoes native audio-in unification; keeps three model stacks.
- **(B) RECOMMENDED FUTURE PILOT — adopt Gemma 4 12B as the *vision + voice-in* model only
  (replace Qwen3-VL **and** Whisper STT), leave the text role on Qwen3-14B.**
  Captures the unique audio-unification upside, contains the blast radius to the
  already-Fail-Soft VLM seam (a failed Gemma load simply degrades to the placeholder), and
  does **not** touch the security-critical PA harness or the mandatory text spec-decode.
  *Gate:* only when an **encoder-free-12B OpenVINO GPU (INT4) path** exists and loads on Arc.
  *Open question to resolve at pilot:* memory co-residency of a 12B VLM + the 14B (already the
  tightest spot in the budget).
- **(C) Full unification — Gemma 4 12B for *all* roles (text + vision + voice).**
  Highest ambition, highest risk. Blocked today on every gating item (OpenVINO 12B path, MTP
  spec-decode, PA harness rebuild). Only consider if BlarAI ever contemplates leaving the
  Qwen3 family wholesale, and only after (B) succeeds.

**Concrete re-evaluation trigger (suggested):** revisit when **all three** are true —
(1) a pre-converted **`Gemma-4-12B` INT4 OpenVINO IR** (encoder-free) is published or
reproducibly exportable via Optimum-Intel; (2) it **loads and runs on the Arc 140V GPU** in a
non-nightly OpenVINO release; (3) a **draft/MTP speculative-decoding path works under OpenVINO
GenAI** (or measured autoregressive tps on Arc clears the incumbent's bar). Until then, the
incumbent set is the correct roadmap.

---

## 10. What I verified vs. what remains open (intellectual-honesty ledger)

**Independently verified for this report:**
- BlarAI's model roles, devices, locks — from ADR-005/006/010/011/012/015/017 and the live
  `shared/inference/` + `services/voice/` source.
- Qwen3-14B specs — Hugging Face model card (14.8B, 40L, GQA 40/8, 151,936 vocab, 32K/131K).
- Qwen3-VL line — QwenLM/Qwen3-VL repo (DeepStack, Interleaved-MRoPE, 256K→1M, sizes).
- Gemma 4 12B architecture/uniqueness — Google developer guide + Maarten Grootendorst's
  visual guide (encoder-free, raw patch/audio projection, 3,840 hidden, MTP, Apache-2.0).
- OpenVINO Gemma 4 status — OpenVINO-toolkit Medium guide + Intel community + OpenVINO GenAI
  supported-models page (functional preview, family = E2B/E4B/26B-A4B/31B, CPU-first,
  GPU-nightly; Gemma3 multimodal INT4-OV exists; 12B not enumerated).
- MTP spec-decode reality — vLLM MTP docs + NVIDIA forum thread (vLLM/CUDA, `transformers`
  dev build, separate assistant checkpoint).

**Open / unverified (flagged, not assumed):**
- Exact INT4 on-disk size and Arc tps of a *hypothetical* OpenVINO Gemma 4 12B (no artifact to
  measure).
- Whether the encoder-free 12B's raw-audio/raw-patch paths are *technically* exportable to
  OpenVINO IR at all today (the enablement gap is inferred from timing + the enumerated family,
  not from a failed export I ran).
- The 12B's own benchmark numbers on BlarAI-relevant tasks (only Google's "near-26B-MoE" claim
  is attributable).
- Co-resident memory cost of any 12B alongside the 14B (the same measurement ADR-015 already
  flags as open for Qwen3-VL).

---

### Source list

- BlarAI: `docs/adrs/ADR-005`, `ADR-006`, `ADR-010`, `ADR-011`, `ADR-012`, `ADR-015`;
  `shared/inference/vlm.py`, `shared/inference/shared_pipeline.py`,
  `services/voice/src/engine.py`; `PERFORMANCE_LOG.md`; `OpenVINO_GENAI_Supported_LLM_Models.csv`.
- Qwen3-14B — https://huggingface.co/Qwen/Qwen3-14B
- Qwen3-VL — https://github.com/QwenLM/Qwen3-VL
- Gemma 4 12B developer guide — https://developers.googleblog.com/gemma-4-12b-the-developer-guide/
- Gemma 4 12B visual guide — https://newsletter.maartengrootendorst.com/p/a-visual-guide-to-gemma-4-12b
- Gemma 4 on OpenVINO — https://medium.com/openvino-toolkit/running-gemma-4-with-openvino-building-a-multimodal-assistant-end-to-end-37a9ce74f0ca
- OpenVINO GenAI supported models — https://openvinotoolkit.github.io/openvino.genai/docs/supported-models
- Gemma 4 MTP (vLLM) — https://docs.vllm.ai/en/latest/features/speculative_decoding/mtp ; vLLM PR #41745
- Gemma 4 vs Qwen benchmarks (flagship sizes) — https://ai.rs/ai-developer/gemma-4-vs-qwen-3-5-vs-llama-4-compared

---
---

## 11. ADDENDUM B — The Consolidation Question (LA reframe)

**Context for this addendum.** The LA pushed back on §0–§10 with two correct points:

1. *"We don't want to stop a model upgrade simply because we'd have to redo the
   current-model-specific security harness."* — Agreed. The harness rebuild is **normal
   upgrade cost**, not a veto. §1–§10 treated it as a risk; here it is treated as **accepted
   work**.
2. *"OpenVINO support is where we'd open a request ticket to Intel."* — Agreed. Lack of
   OpenVINO support for the encoder-free 12B is **not a permanent wall**; it is a
   **ticket + wait** item. The question is whether the model is good enough to justify
   filing that ticket (and building the harness).

So this addendum answers the *actual* question: **conceptually — setting aside harness and
treating OpenVINO as ticketable — is Gemma 4 12B truly superior enough to consolidate onto?**
Two scenarios, exactly as the LA framed them:

- **Scenario X — Total collapse:** replace the *entire* model stack with **just Gemma 4 12B**
  (text + vision + voice + code).
- **Scenario Y — Near-total collapse:** replace **Qwen3-14B + Whisper-small + Kokoro-82M**
  with **Gemma 4 12B** (i.e. fold text + speech-in + speech-out into one model), leaving
  Qwen3-VL as the only other model.

---

## 12. The One Hard Correction: Gemma 4 12B Cannot Do Speech *Output* (TTS)

This is the single most important new finding, and it reshapes both scenarios. **Verified
against Google's own Gemma 4 audio documentation:**

- Gemma 4 12B's audio is **input only**. It is trained for **ASR (speech-to-text)** and
  **AST (automated speech translation)** — you give it a `{"type": "audio"}` clip, it
  emits **text**. The documented task type is transcription/understanding.
- There is **no speech synthesis** anywhere in the Gemma 4 architecture or docs. A
  decoder-only LLM that *projects audio into its input space* has no vocoder / audio-token
  detokenizer to produce a waveform. It emits text tokens, full stop.
- Additional audio constraints: **max 30 seconds per clip**, **25 tokens per second** of
  audio.

**Consequences for the two scenarios:**

| Capability | Incumbent | Gemma 4 12B can replace it? |
|------------|-----------|------------------------------|
| Text (PA + AO + Code) | Qwen3-14B | **Yes** (with coding caveat — §13) |
| Vision | Qwen3-VL-8B | **Yes** (with maturity caveat — §13) |
| Speech **in** (STT) | Whisper-small | **Yes** — native ASR/AST, *but capped at 30 s/clip* |
| Speech **out** (TTS) | **Kokoro-82M** | **NO — hard architectural gap** |

**Therefore:**
- **Scenario Y as written is not fully achievable.** Gemma 4 12B can absorb Qwen3-14B and
  Whisper-small, **but it cannot absorb Kokoro-82M.** If BlarAI is to *speak*, a TTS model
  (Kokoro or equivalent) is **irreducible**. Revised Scenario Y = "Qwen3-14B + Whisper →
  Gemma; **Kokoro stays.**"
- **Scenario X ("just Gemma 4 12B") is likewise impossible if spoken output is a feature.**
  The minimum consolidated stack with voice is **Gemma 4 12B + a TTS model**, not Gemma alone.
- The **30 s ASR clip limit** also means that for long-form dictation/voice-notes, you would
  either chunk audio or keep Whisper for long-form — Whisper has no such limit. So even the
  STT win is "yes, with an asterisk."

This does **not** sink the consolidation thesis — but it corrects its ceiling. The realistic
prize is **"one model for text + vision + speech-in"** (collapsing 3 models — 14B, VL-8B,
Whisper — into 1), **plus Kokoro for speech-out.** That is still a 4→2 reduction (or 3→2 if
you don't currently count Kokoro), and the memory math (§13) is what makes it compelling.

---

## 13. Is It *Truly Superior* for Consolidation? Honest Axis-by-Axis

Accepting harness rebuild and treating OpenVINO as ticketable, here is the fair scorecard for
"one Gemma 4 12B (+ Kokoro)" vs "Qwen3-14B + Qwen3-VL-8B + Whisper + Kokoro":

| Axis | Verdict | Detail |
|------|---------|--------|
| **Memory footprint** | **STRONG WIN** | One INT4 12B ≈ **~7 GB** (Q4 runs on an 8 GB RTX 4060; bf16 safetensors = 10.2 GB; Google targets 16 GB). Current co-resident worst case is 14B (~8.7 GB) **+** VL-8B (~5 GB) = **~13.7 GB** before KV. Consolidation **roughly halves GPU footprint and resolves the ADR-015 co-residency brick risk outright.** On a ~15.5 GB budget this is the headline win. |
| **Operational simplicity** | **WIN** | One compile, one weight set, one quant pipeline, one model to verify/secure/update/benchmark. For a **decades-long single-user local system**, radical simplification has real compounding value. |
| **Speech-in unification** | **WIN (asterisk)** | Native multilingual ASR + translation folds Whisper away — *except* 30 s/clip cap and 25 tok/s cost; long-form may still want Whisper. |
| **Context window** | **WIN on paper** | 256K-class vs Qwen3-14B's 32K native / 131K YaRN. (Real-world long-context retrieval unverified for the 12B.) |
| **Encoder-free latency** | **WIN** | No ViT/conformer pre-pass; multimodal tokens hit the decoder immediately → lower first-token latency than encoder-based Qwen3-VL. |
| **Text/reasoning quality** | **PLAUSIBLE WIN — UNVERIFIED** | Gemma 4 is a large generational leap; the 12B is "near 26B-MoE quality." Could match or beat Qwen3-14B on reasoning. **But the flagship numbers are the 31B/26B-A4B, not the 12B**, and the 12B's own BlarAI-task quality is unmeasured. |
| **Vision — document understanding (DocVQA/InfoVQA)** | **PARITY / POSSIBLE WIN** | **Corrected — see §13.1.** Reported Gemma 4 12B: **InfoVQA 88.4** (≈ matches the 26B), **DocVQA ~94** (trails the 26B's 94.9 *closely*), **MMMU-Pro 69.1**. Coverage explicitly credits the **encoder-free design** for document understanding. This is *not* a weak document model. |
| **Vision — pure multi-language OCR extraction** | **NARROW QWEN EDGE (track-record, unverified head-to-head)** | The Qwen-VL *lineage* is the reference open OCR family (independent OCR benchmark: Qwen2.5-VL 72B/32B beat OCR-specialized mistral-ocr); Qwen3-VL ships 32-language OCR + dedicated doc-parsing tooling (Qwen-HTML, layout/bbox). That is *proven productized maturity*, **not** architectural superiority — and it is **unverified for the 8B vs the 12B**. Gemma may even **beat** Qwen at *handwriting* (sub-benchmark reports). |
| **Vision — long-document context** | **NARROW QWEN EDGE** | Qwen3-VL 256K→**1M** vs Gemma **256K**. Both are 256K-class for practical use; Qwen extends further. Gemma 4's 256K is reported as *actually usable* (Gemma 3→4 fixed the "theoretical-only" long-context problem). |
| **Coding (USE-CASE-005)** | **CAVEAT / POSSIBLE REGRESSION** | Community consensus: the 12B was **"almost certainly not trained for coding"** ("nowhere in the announcement is coding mentioned"); "better than a full-precision 9B" but people still reach for Qwen3.5-9B+ for code. **The Code Agent is the role most at risk** in a full collapse. |
| **Agentic / function calling** | **PARITY** | Both strong. Gemma 4 native JSON function calling + thinking mode ≈ Qwen3 tool-calling for BlarAI's purposes. |
| **Speculative decoding** | **NEUTRAL — ticket item** | 12B ships **MTP out-of-the-box** (first Gemma to). Good *if* OpenVINO GenAI gains an MTP (or draft) path on Arc — part of the Intel ask. Today MTP is vLLM/CUDA. |
| **Determinism** | **OK** | Greedy/temp=0 supported — compatible with the security-classifier mandate. |
| **Licensing** | **PARITY** | Both Apache-2.0. |
| **Fault isolation** | **LOSS** | Today a vision or voice model failure degrades **independently** (Fail-Soft). One model serving everything = **one blast radius**: a bad load/regression takes down text + vision + voice at once. Consolidation trades resilience for simplicity. |

**Net:** On the axes that dominate a **local, memory-constrained, decades-long** system —
**memory, simplicity, unification, context, latency** — Gemma 4 12B has a **genuinely strong
consolidation case**, arguably superior to the status quo. The real losses narrow to **coding**,
**fault isolation**, a **pile of "unverified-for-the-12B" quality claims**, and a **narrow Qwen
edge in proven multi-language OCR-extraction pipelines + 1M context**. None of those are
disqualifying; all of them are **measurable before commit.**

---

## 13.1. Correction — "Vision OCR/long-doc maturity favors Qwen3-VL" does NOT hold as stated

*The LA challenged the Addendum-B claim that "Vision OCR/long-doc maturity still favors
Qwen3-VL." On re-examination against benchmark data, that flat claim is **retracted**. This
subsection records the challenge and the corrected position, because not-rubber-stamping a
prior conclusion is a project value.*

**Why the original claim was wrong (two errors):**
1. **Incumbent-maturity heuristic.** I leaned on "Qwen3-VL is in-product and proven; Gemma is
   3 days old" and let that stand in for a capability judgment. That is a track-record
   argument, not a capability argument.
2. **DocVQA ≠ OCR conflation.** I treated "document understanding" and "OCR text extraction"
   as one axis. They are different: **DocVQA/InfoVQA** = *answer a question about a document*
   (understanding + reasoning); **OCR** = *transcribe the text verbatim*. Gemma 4 12B's
   strength is clearest on the former.

**What the evidence actually shows:**
- Gemma 4 12B is **strong on document understanding** — InfoVQA **88.4** (≈ the 26B), DocVQA
  **~94** (just behind the 26B's 94.9), MMMU-Pro **69.1** — and the encoder-free spatial-token
  design is *credited* for it, not blamed. So "Qwen is more mature on documents" does not
  survive as a blanket statement.
- Gemma may **beat** Qwen at **handwriting** recognition (independent sub-benchmark reports).
- **Where Qwen3-VL keeps a *narrow* edge:** (a) **proven, productized multi-language OCR
  *extraction*** — the Qwen-VL family is the empirical reference (it beat OCR-specialized
  models on an independent 1,000-document OCR benchmark), with 32-language OCR and dedicated
  document-parsing output formats; (b) the **1M context ceiling** (vs Gemma's 256K). Both are
  **track-record / ceiling** advantages, **not** demonstrated 8B-vs-12B superiority.

**Corrected position:** On *document understanding*, Gemma 4 12B is **competitive-to-better**.
Qwen3-VL's remaining edge is **narrow and specific** — proven multi-language OCR-extraction
pipelines and a higher context ceiling — and it is **unverified head-to-head (8B vs 12B)**. The
tie-breaker is a **bake-off on BlarAI's real images**, not model lineage. Two caveats kept for
honesty: the Gemma numbers are *reported, not yet confirmed* by an official table; and the
encoder-free coarse-patch design (48×48 patches, token budget 70–1120) *theoretically* risks
losing fine dense-text detail — but the DocVQA/InfoVQA scores suggest that is not a fatal
problem in practice.

---

## 14. Revised Recommendation (Addendum B)

**Yes — file the Intel ticket. The consolidation upside is real and the ticket is cheap,
high-option-value, and strategically aligned. Pursue it in parallel with a quality bake-off,
and commit only if the bake-off verifies.** This supersedes §9's "watch / don't-act" posture
in light of the LA's two reframes.

Rationale: the memory halving + single-model simplicity + audio/vision/text unification +
bigger context, on a system whose whole identity is "one local model stack for decades," is
exactly the kind of bet worth de-risking now rather than letting age. The two things that were
"blockers" in §0–§10 are, per the LA, *work items* (harness) and *a request* (Intel), not
walls.

**What to actually ask Intel for (scope the ticket precisely — this is 3 asks, not 1):**
1. **Encoder-free Gemma 4 12B → OpenVINO IR, INT4, on Arc 140V GPU**, runnable via
   `VLMPipeline`/GenAI (the *unified/encoder-free* 12B specifically — *not* the already-enabled
   encoder-based E2B/E4B/26B-A4B/31B family).
2. **Audio-input enablement** for that path in OpenVINO GenAI (raw-waveform projection is brand
   new; confirm the audio modality is exportable + runnable, not just image+text).
3. **Speculative decoding** for it on OpenVINO — **MTP** (the 12B's native assistant
   checkpoint) **or** a generic draft-model fallback — since spec-decode is mandatory for
   acceptable 14B-class tps on Arc (ADR-012).

**Run these in parallel with the ticket (no Intel dependency, decides go/no-go):**
- **A text-quality bake-off** of Gemma 4 12B vs Qwen3-14B on BlarAI's *own* corpora — above
  all the **Policy Agent agreement gate** (the security classifier must hold ≥ its current
  0.9483) and the **Code Agent** tasks (the most likely regression).
- **A vision bake-off** on real landscaping photos (describe/identify) vs Qwen3-VL-8B,
  including any OCR the use cases need.
- **An STT check**: does the 30 s clip cap + 25 tok/s cost meet the voice use cases, or must
  Whisper stay for long-form?
- These can run **today** on CPU/GPU via Hugging Face Transformers or llama.cpp (Q4 GGUF) —
  no OpenVINO needed to judge *quality*. OpenVINO is only needed for *production runtime*,
  which is what the ticket buys.

**Go / no-go criteria (commit to the roadmap only if all hold):**
1. Gemma 4 12B text quality **≥ Qwen3-14B** on the PA gate and AO tasks (security floor
   non-negotiable).
2. Coding quality acceptable for UC-005, **or** UC-005 explicitly stays on a Qwen coder
   (partial consolidation is fine).
3. Intel returns a **GPU INT4 path with working spec-decode** (or measured autoregressive
   Arc tps clears the incumbent bar).
4. Consolidated memory **measured** lower co-resident (expected, but verify the brick risk is
   actually gone, not moved).
5. A conscious decision is taken to **accept reduced fault isolation** (one model, one blast
   radius) — or to keep vision/voice on a Fail-Soft secondary.

**The honest one-liner for the LA:** *Gemma 4 12B is a credible — possibly superior —
consolidation target that could take BlarAI from four models to two (Gemma + Kokoro). It
cannot do text-to-speech, so Kokoro is permanent; its coding is the likeliest regression; and
its 12B-specific quality is unproven. On documents it actually looks competitive-to-better (see
§13.1) — Qwen3-VL's remaining vision edge is narrow (proven multi-language OCR-extraction
pipelines + a 1M context ceiling). The Intel ticket is clearly worth filing; just don't commit
the roadmap until a same-day, no-Intel-needed quality bake-off confirms it actually beats what
you already run.*

### Addendum B — verified vs open

**Verified for this addendum:**
- Gemma 4 12B audio is **input-only ASR/AST** (no TTS), 30 s/clip, 25 tok/s — Google Gemma 4
  audio guide.
- INT4 footprint ~7 GB (Q4 on 8 GB RTX 4060; bf16 safetensors 10.2 GB; 16 GB target) — Ars
  Technica, Unsloth/Reddit, HF run guide.
- 12B ships **MTP out of the box** — Ars Technica.
- Coding not a training focus for the 12B — Hacker News thread consensus.
- Gemma 4 12B **document-understanding** scores (reported, not yet in an official table):
  **InfoVQA 88.4, DocVQA ~94 (26B 94.9), MMMU-Pro 69.1** — Labellerr/BuildFastWithAI readouts
  of Google's launch chart. Refutes the §13-original "Qwen more mature on documents" claim.
- Qwen-VL family is the empirical reference for **OCR extraction** (beat OCR-specialist models
  on an independent 1,000-doc benchmark) — getomni.ai OCR benchmark; Qwen3-VL 32-language OCR
  + doc-parsing cookbooks — QwenLM/Qwen3-VL.

**Open / unverified (must be measured before commit):**
- 12B text quality vs Qwen3-14B on BlarAI's PA/AO corpora (the security floor).
- 12B coding quality for UC-005.
- 12B vision/OCR vs Qwen3-VL-8B on BlarAI's real images — **head-to-head 8B-vs-12B is
  unverified; §13.1 narrowed but did not close this** (Gemma numbers are reported-not-confirmed;
  pure OCR-extraction parity untested on Arc).
- Whether the encoder-free coarse-patch design loses fine dense-text detail in practice.
- Whether Intel will (and how fast) deliver the encoder-free-12B INT4 GPU + audio + spec-decode
  path.
- Consolidated co-resident memory measured on Arc.

### Addendum B — added sources

- Gemma 4 audio (ASR/AST, input-only, 30 s, 25 tok/s) — Google AI for Developers, Gemma 4
  audio understanding guide.
- Gemma 4 12B runs on 16 GB laptops / MTP out-of-the-box — Ars Technica,
  https://arstechnica.com/google/2026/06/googles-new-gemma-4-open-ai-model-is-sized-for-your-laptop
- Q4 footprint / local runs — Unsloth via r/LocalLLM; "I ran Gemma 4 12B on an RTX 4060
  Laptop" (Q4_K_M GGUF).
- 12B coding not a focus — Hacker News discussion id=48385906.
- Gemma 4 12B document-VQA numbers (InfoVQA 88.4 / DocVQA ~94 / MMMU-Pro 69.1) —
  https://www.labellerr.com/blog/gemma-4-12b-run-locally-and-fine-tune ;
  https://www.buildfastwithai.com/blogs/gemma-4-12b-guide
- Open-source OCR-extraction benchmark (Qwen-VL family leads) — https://getomni.ai/blog/benchmarking-open-source-models-for-ocr
- Gemma-vs-Qwen document-AI sub-benchmark (handwriting) — r/LLMDevs thread on Gemma 4 vs Qwen3.5 document AI.
