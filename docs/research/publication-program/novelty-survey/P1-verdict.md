---
title: "P1 novelty + venue survey verdict — The Lunar Lake local-AI performance corpus"
status: survey-verdict
area: research
piece: P1
tier: technical / data-first
portfolio_purpose: OV (OpenVINO / hardware community standing)
surveyor_pass: Phase 0 novelty + venue survey
survey_date: 2026-07-19
all_urls_access_dated: 2026-07-19
---

# P1 — The Lunar Lake local-AI performance corpus

Survey run per AUTHOR_KIT §I. All URLs accessed 2026-07-19. Project facts sourced only
from VERIFIED_FACTS.md; one **material discrepancy** with that sheet was discovered
during the survey and is flagged in §2 and §5 (our own OpenVINO GitHub Discussion
#36484). Recency window applied: hardware/model performance = hard 18-month scan
(§I.2), i.e. roughly 2025-01 → 2026-07.

---

## 0. Material finding up front (read first)

**One of P1's candidate contributions is already partially published — by us.**
OpenVINO GitHub **Discussion #36484**, author **blairducrayoppat** (the LA's handle),
posted **2026-06-20**, is a speculative-decoding characterization on the exact P1 box
(Core Ultra 7 258V / Arc 140V, OpenVINO 2026.1.0). It is **not in VERIFIED_FACTS.md**.
This is our own footprint, not prior-art-by-others, and it reshapes both the novelty
call for the spec-decode sub-piece and the OpenVINO-venue fit (proven posting
precedent). Verification method: rendered-HTML read via WebFetch (author attribution
unambiguous). GitHub Discussions are GraphQL-only in the API, so the author session must
re-confirm authorship/date via the GraphQL endpoint before any external citation
(AUTHOR_KIT §B). Recommend the editorial board add #36484 to VERIFIED_FACTS.

---

## 1. Prior-art map

Axes for PRIOR ART (§I.1): (a) thesis, (b) evidence type, (c) audience. Overlap on all
three = prior art; one or two = related work. Nothing found overlaps on all three.

| # | Who / what | Where | When | Tier | Overlap with P1 | Class |
|---|---|---|---|---|---|---|
| A | **blairducrayoppat — "GPU-target + NPU-draft speculative decoding on Lunar Lake"** (Discussion #36484). Qwen3-14B INT4 target + Qwen3-0.6B INT4 draft; GPU-only 12.2 tok/s, CPU-draft 1.35×, NPU-draft 0.55–0.74×; n=3, single prompt, explicit limits stated | [openvinotoolkit/openvino discussion #36484](https://github.com/openvinotoolkit/openvino/discussions/36484) | 2026-06-20 | T1 (first-party, **ours**) | Spec-decode on the same box; **same author** | **Our own prior work** — build on, don't duplicate |
| B | **Georganas, Kalamkar, Heinecke (Intel Labs) — "Pushing the Envelope of LLM Inference on AI-PC and Intel GPUs"** — includes Core Ultra 7 258V + Arc 140V; Falcon3-1B / MobileLLM-1.5B / Llama3-8B; 1/2/4-bit MXFP4 kernels; up to 7× low-bit speedup | [arXiv 2508.06753v2](https://arxiv.org/html/2508.06753v2) | Aug 2025, rev Jan 2026 | T1 (peer-track) | Same silicon | **Related work** — thesis is low-bit GEMM/GEMV kernels, not a field corpus; no KV/co-residency/NPU-embed/MoE/spec-decode |
| C | **Intel — "Intel AI Solutions Accelerate Qwen3 LLMs"** — first-party enablement; Qwen3 on Intel platforms incl. a Core Ultra 7 (Lunar Lake) config, OpenVINO 2025.2.0-dev *(full page returned HTTP 403; characterized from Intel's search-indexed summary — see §5 gap)* | [intel.com Qwen3 article](https://www.intel.com/content/www/us/en/developer/articles/technical/accelerate-qwen3-large-language-models.html) | 2025 (undated on snippet) | T1 (first-party marketing/enablement) | Same model family + chip | **Related work** — vendor enablement numbers, not an independent instrumented corpus |
| D | **TechHara — "Local LLM Benchmark on Intel Lunar Lake"** — 258V/140V, llama.cpp (Vulkan/SYCL/IPEX-LLM), Ministral-3B F16/Q8/Q4; prefill ~2× M1 Pro, decode ~M2; one-off | [Medium](https://medium.com/@techhara/local-llm-benchmark-on-intel-lunar-lake-133c39f10455) | 2025-12-07 | T2 (practitioner blog) | Same chip, personal register | **Related work** — single snapshot, llama.cpp only, none of P1's advanced dimensions |
| E | **Nikolay Falaleev — "Performance Analysis of Intel iGPUs in VLM and LLM applications"** — Ultra 5 125H (Meteor Lake, Arc Xe-LPG), IPEX-LLM/Ollama; big models, std-dev methodology; NPU "in future posts" | [nikolasent.github.io](https://nikolasent.github.io/hardware/deeplearning/2025/02/09/iGPU-Benchmark-VLM.html) | 2025-02-09 | T2 (practitioner GH-Pages blog) | Intel iGPU LLM benchmarking, personal blog | **Related work** — different chip (MTL, not LNL), different runtime, single snapshot; also a **venue exemplar** (§4E) |
| F | **JoshCork — intel-ai-benchmarking** — standardized harness across ADL/LNL/MTL; OpenVINO IR, Llama-3.1-8B INT4; TTFT/throughput/percentiles to a SQLite results DB | [GitHub](https://github.com/JoshCork/intel-ai-benchmarking) | undated (31 commits) | T2 (tooling repo) | "Structured Intel benchmark corpus" spirit | **Related work** — a harness, not a published analysis; no KV/co-residency/NPU-embed/MoE/spec-decode |
| G | **Bibek Poudel — "How to Run Qwen3.6-27B Locally on Intel Arc Pro B70: What Actually Works"** — Arc Pro B70 (discrete), "what actually works" field register | [Medium](https://bibek-poudel.medium.com/how-to-run-qwen3-6-27b-locally-on-intel-arc-pro-b70-what-actually-works-c96dec67c6f7) | 2026 (recent) | T2 | Intel-GPU field-report register | **Related work** — discrete GPU, not the LNL iGPU heterogeneous stack |
| H | **NITRO — "LLM Inference on Intel Laptop NPUs"** — LLM decode *on the NPU*, >10× vs Intel NPU Accel Library | [arXiv 2412.11053](https://arxiv.org/pdf/2412.11053) | 2024-12 | T1 | NPU compute on the same class of laptop | **Related work** — NPU runs the *LLM*; P1 runs *embeddings* on NPU and the LLM on GPU (opposite split) |
| I | **"Neural-Hacker" — "Understanding NPUs with OpenVINO: Real Capabilities, Limitations & ML Use Cases"** | [huggingface.co/blog/Neural-Hacker/openvino](https://huggingface.co/blog/Neural-Hacker/openvino) | 2025 | T2 (HF community blog) | NPU capabilities/limits, honest register | **Related work** — capabilities explainer, not measured offload data; also a **venue exemplar** (§4B) |

Adjacent context (not competition): OpenVINO's own spec-decode Medium post
([link](https://medium.com/openvino-toolkit/accelerating-llm-inference-with-speculative-decoding-using-openvino-genai-api-d965dfbb443e), T1);
FastDraft docs; OpenVINO Model Hub benchmark tables (T1); community perf issue
[#32306 "265k NPU much slower than CPU"](https://github.com/openvinotoolkit/openvino/issues/32306)
(T3, shows demand for honest NPU-vs-CPU numbers). Cloud/datacenter KV-cache and
multi-model-serving literature (KVQuant, KVDrive, vLLM colocation, SLINFER) is a
different world (big-GPU serving) and not competition for a single-box iGPU corpus.

---

## 2. The gap

No published item overlaps P1 on thesis + evidence + audience. What the named prior art
**lacks**, and P1 has:

1. **Multi-model co-residency telemetry on one shared-memory Lunar Lake box — genuine
   white space.** Targeted searches for co-residency on a 32 GB iGPU returned only
   generic "make it fit in VRAM" guidance and cloud/datacenter serving papers — nobody
   has published *measured* telemetry for a heterogeneous local stack (resident 14B +
   INT4 draft + NPU embeddings + Whisper + on-demand SDXL) with the In-Use = Total −
   Available accounting and the explicit evict-and-lazily-reload discipline. This is
   P1's crown jewel and should lead.
2. **A longitudinal, instrumented single-system field corpus**, versus the one-off
   snapshots (D, E) and the un-published harness (F). The strength is exactly the n=1
   discipline the Author Kit mandates: every number dated, conditioned, and reproducible
   from `docs/performance/*.json`.
3. **Honest superseded-figure discipline** — carrying the 1.2× draftless-vs-draftless
   cross-runtime number *alongside* the flattering 1.8× spec-on figure. None of D–H
   publishes its own supersessions; vendor material (B, C) never does.
4. **Upstream-fix provenance** — the #725 crash → openvino.genai **PR #4082 merged
   2026-07-08** arc gives P1 a citable, API-verifiable "we found it, fixed it, it
   landed" spine that no benchmarking blog or harness has.
5. **The heterogeneous-split NPU story is the inverse of the hype** — P1 puts
   *embeddings* on the NPU (13.6× on document-window texts) and keeps LLM decode on the
   GPU, with the honest "NPU is ~3.6× slower than CPU for small-model decode" context
   already recorded in #36484. Prior art (H, I) and community demand (#32306) show the
   field wants exactly this honesty and mostly gets NPU-LLM hype instead.

What is **NOT** a gap (do not lead here): raw "Qwen / Llama tok/s on Lunar Lake" is
covered by Intel first-party (C), the arXiv paper (B), and TechHara (D). Leading with
headline throughput numbers walks straight into saturated territory and vendor
comparison. Lead with integration, co-residency, and discipline; use the raw numbers as
supporting evidence, positioned against B/C/D by name.

---

## 3. Verdict

**GO (strong) — RESHAPE into a series; do not publish as one "here are my Lunar Lake
benchmarks" post.**

Reasoning an OpenVINO-community expert would accept: the individual measurement *types*
each have adjacent published work, so a generic benchmark dump would be a me-too. But
the **combination** — co-residency telemetry (unpublished elsewhere), the instrumented
single-box field corpus, the superseded-figure honesty, and the merged-upstream-fix
provenance — is differentiated and directly serves the OV-standing purpose. The
reshape is what turns "another Lunar Lake benchmark" into "the reference field corpus
for a heterogeneous local-AI stack on this silicon."

**Recommended series carve** (home base = canonical long-form; syndicate per §4). The
`docs/performance/*.json` dataset is the through-line — every post links its rows:

- **S1 — Co-residency on one 32 GB Lunar Lake box** *(lead; most novel)*. Multiple
  models resident at once; the memory ceiling, In-Use accounting, and the
  evict/lazily-reload discipline. This is the post nobody else has written.
- **S2 — The honest speculative-decode ledger**. Expands and **cites #36484**; the
  draft-model A/B, the 1.2× draftless-vs-draftless cross-runtime number, and the
  superseded-figure discipline. Reconcile #36484's 128-token-budget numbers against the
  VERIFIED_FACTS 16K-context figures (they are *different experiments* — say so).
- **S3 — NPU embedding offload, honestly**. 13.6× on document-window embeddings + the
  heterogeneous split + the "NPU is slower for LLM decode" counter-context. Positions
  against NPU-LLM hype (H, I, #32306).
- **S4 — The crash we found and fixed upstream** (#725 → PR #4082). Short, narrative,
  reproducible; strongest single OV-standing artifact and a tonal bridge to P2/P3.

The KV-cache two-regime sweep and the MoE comparisons are best distributed as evidence
inside S1–S2, or collected into an optional fifth "methods + dataset tour" post if the
material is deep enough at author time. **Sequencing:** S4 or S1 first (S4 is the
credibility handshake with the OpenVINO maintainers; S1 is the strongest novelty) —
author's call at Phase 1.

---

## 4. Venue fit

Purpose is OV standing, so the OpenVINO-adjacent channels (4C/4D) and the practitioner
crowd (4A) are the center of gravity; home base (4E) is canonical; HF (4B) is high-value
syndication.

### 4A. r/LocalLLaMA — good fit for S1/S3/S4, high sensitivity to self-promo

- **Fit:** strong. Benchmarks, self-hosting guides, and honest hardware write-ups are
  core content, and Lunar Lake / Intel-iGPU local inference is an active, under-served
  topic there. This is the widest practitioner reach for P1.
- **Submission mechanics:** standard subreddit text/link post; no karma/age gate is
  documented on any primary page I could reach (see the gap below). Reddit account
  required (out of scope for program sessions until an LA-approved posting action).
- **PRIMARY-RULES GAP (must flag, per §I.5):** the subreddit's own rules page could not
  be retrieved. WebFetch is tool-blocked for `old.reddit.com`, `www.reddit.com`, and the
  `.../about/rules.json` endpoint; the Chrome browser route was unavailable (extension
  not connected). **Reasonable primary alternates are exhausted — the rule text below is
  NOT primary-verified.** From secondary aggregators (T3, marketing/self-promo-checker
  sites — [LaunchWake](https://www.launchwake.com/channels/r-localllama),
  [Intoru](https://intoru.ai/subreddits/localllama)) and well-established community norm:
  self-promotion is *tolerated but policed* — lead with technical value, keep promotion a
  small fraction of activity (~10% cited), **no link in the title**, engage in comments,
  and no bare product pitches. **Action for the author/LA:** confirm the live rules
  (esp. any self-promotion / blog-link rule and any "no low-effort benchmark" clause)
  directly from the subreddit before any approved post — do not rely on this paragraph.
- **Gold-standard exemplars:** I could not surface specific r/LocalLLaMA post URLs
  (Reddit is poorly indexed by the search tool and every reddit-scoped query returned no
  links). The exemplar *genre* to match: a titled hardware field-report that leads with
  a methods table and the dataset link, answers reproduction questions in-thread, and
  mentions the home-base blog only as the "full data here" footer. **Flagging this as an
  exemplar gap** the author should fill from inside the subreddit.

### 4B. Hugging Face community blog — strong fit, clean primary mechanics

- **Fit:** strong for S1–S3 (and the dataset). HF's two allowed categories map exactly
  onto P1: "explore an AI science or engineering concept" (co-residency, spec-decode,
  NPU offload) and "announce the release of an open source artifact" (the reproducible
  performance dataset). Auto-linking surfaces the article on any referenced model/dataset
  repo page — a discovery bonus if the dataset is a Hub repo.
- **Mechanics (primary — [huggingface.co/docs/hub/en/blog-articles](https://huggingface.co/docs/hub/en/blog-articles),
  access 2026-07-19):** create at `huggingface.co/new-blog`, Markdown, publish under user
  or org namespace. **Requirement, quoted:** to publish under a personal namespace "you
  need a confirmed email" and must have "an active PRO subscription" **or** be a member of
  a Team/Enterprise org with write/admin role. Org-namespace publishing needs a
  Team/Enterprise org + write/admin role. **Content rule, quoted:** "Avoid advertising
  paid solutions in your posts," and all articles are "subjected to content guidelines of
  Hugging Face Hub," which HF "reserves the right to take down." No pre-publication review
  gate documented. **Note for LA:** personal-namespace publishing appears to require a PRO
  (paid) account today — a small standing decision, not a technical blocker.
- **Gold-standard exemplars (the docs' own cited examples + a topical community one):**
  [KV Caching Explained (not-lain)](https://huggingface.co/blog/not-lain/kv-caching) —
  the bar for a clear engineering-concept explainer;
  [Get your VLM running in 3 steps on Intel CPUs (openvino-vlm)](https://huggingface.co/blog/openvino-vlm) —
  Intel/OpenVINO benchmark-forward post (TTFT 0.42 s, 47 tok/s) that is the register to
  match for OV-audience credibility;
  [Understanding NPUs with OpenVINO (Neural-Hacker)](https://huggingface.co/blog/Neural-Hacker/openvino) —
  a *community-namespace* honest NPU capabilities/limits post, proof the exact P1 angle
  lands on this venue.

### 4C. OpenVINO community blog (blog.openvino.ai) + Medium (medium.com/openvino-toolkit) — best-fit for OV standing, engagement-first

- **Fit:** strongest for the OV-standing purpose. Two surfaces: the community blog
  **blog.openvino.ai** and the curated **Medium publication**. Both routinely run
  exactly P1's genre (perf write-ups, benchmark tours, integration stories).
- **Mechanics:** the Medium publication is **editor-curated** — posts are bylined
  "OpenVINO toolkit," i.e. you don't self-publish; you coordinate with the OpenVINO
  DevRel team to be added/featured. The docs invite non-code contributions broadly
  ("Articles, tutorials, blog posts, demos, videos … more than welcome," per
  [How to contribute to an AI open-source project](https://medium.com/openvino-toolkit/how-to-contribute-to-an-ai-open-source-project-c741f48e009e))
  and say to "reach out to OpenVINO developers"/documentation maintainers for content
  help. *(The 2026 docs contributing page — [contributing.html](https://docs.openvino.ai/2026/about-openvino/contributing.html) —
  rendered nav-only via WebFetch; the contribution-invitation language above is from the
  DevRel Medium article, T2.)* This **matches our own engagement-first doctrine**: open
  a thread / coordinate before submitting. And #36484 proves the door is already open to
  the LA's handle in the OpenVINO GitHub space.
- **Gold-standard exemplars:**
  [Accelerating LLM Inference with Speculative Decoding using OpenVINO GenAI](https://medium.com/openvino-toolkit/accelerating-llm-inference-with-speculative-decoding-using-openvino-genai-api-d965dfbb443e) —
  directly topical to S2; the register and depth to match;
  [Introducing OpenVINO Model Hub: Benchmark AI Inference with Ease](https://medium.com/openvino-toolkit/introducing-openvino-model-hub-benchmark-ai-inference-with-ease-2cd7ad8f5e4d) —
  the benchmark-presentation bar;
  [Ollama Integrated with OpenVINO, Accelerating DeepSeek Inference](https://blog.openvino.ai/blog-posts/ollama-integrated-with-openvino-accelerating-deepseek-inference) —
  a blog.openvino.ai community integration post, the home-turf format.

### 4D. Intel Community blog (community.intel.com) — LOW fit as a posting venue

- **Fit:** low for *self-publishing*. The AI blogs at
  [community.intel.com/t5/Blogs](https://community.intel.com/t5/Blogs/ct-p/blogs) read as
  Intel-staff-authored; no external guest-author submission path is documented. The
  relevant *program* is the AI PC Developer Program (a relationship/enablement track, not
  a blog channel). **Recommendation:** do not target Intel Community as a P1 posting
  venue; treat it as a place P1's data could be *cited/engaged* and the AI PC Developer
  Program as a possible later relationship. Deprioritize.

### 4E. Personal GitHub Pages blog (home base) — canonical, ideal fit, no rules

- **Fit:** ideal and already-decided as home base (README §1). Zero new infrastructure
  on the existing public mirror; canonical URLs the LA owns; every community post links
  back here. No venue rules apply (self-owned).
- **Exemplar (genre bar):** [nikolasent.github.io iGPU benchmark post](https://nikolasent.github.io/hardware/deeplearning/2025/02/09/iGPU-Benchmark-VLM.html) —
  a personal GH-Pages-hosted Intel-iGPU benchmark blog with std-dev methodology and a
  "future posts" series structure; the closest template for what P1's home base should
  look like, and a reminder the bar to clear is depth + honesty, not novelty of chip.

---

## 5. Piece-specific risks

1. **Self-duplication / provenance (highest):** #36484 already publishes spec-decode
   numbers under the LA's handle and is missing from VERIFIED_FACTS. Risk: S2 restates
   or *contradicts* it. Mitigation: cite it, reconcile the 128-token vs 16K experiments
   explicitly, and get it into VERIFIED_FACTS + GraphQL-confirmed before print.
2. **Saturated-angle trap:** raw Qwen/Llama-on-Lunar-Lake tok/s is covered by Intel
   (C), arXiv (B), and TechHara (D). Leading with headline throughput invites "vendor
   already published this / your numbers differ from Intel's." Mitigation: lead with
   co-residency and discipline; position raw numbers against B/C/D by name; never imply
   generality (n=1).
3. **Superseded-figure hazard (AUTHOR_KIT §B trap 3):** the 14B decode figures and the
   cross-runtime comparison have supersessions/addenda in PERFORMANCE_LOG. Always cite
   the latest entry + both sides of the 1.8×/1.2× pair. A stale flattering number is the
   single most likely fatal error here.
4. **Upstream-state drift (§B trap 2):** "PR #4082 merged 2026-07-08" is API-verified;
   **release-inclusion is UNVERIFIED** (VERIFIED_FACTS). Do not write "shipped in release
   X" without checking tags/release notes on the day of print.
5. **Vendor-relations tone:** the honest "NPU is slower than CPU/GPU for small-model
   decode" and any llama.cpp-vs-OpenVINO comparison must stay collaborative-upstream, not
   vendor-bashing (AUTHOR_KIT §D). Frame as "on this box, with these versions," never as
   a verdict on Intel's NPU or on llama.cpp.
6. **Reddit self-promo rule (unverified):** posting to r/LocalLLaMA without confirming
   the live self-promotion rule risks removal/ban. Mitigation: confirm rules in-venue;
   value-first post, dataset link as footer, engage in comments; LA-approved single
   action only.
7. **Privacy/leak screen (§D):** the box's published spec is fine, but co-residency and
   config posts must not leak local usernames/hostnames/absolute paths or live
   egress/policy-machinery configuration details. Source only from content that clears
   the public-mirror leak gate.
8. **HF PRO-account requirement:** a small standing decision (personal-namespace HF blog
   needs PRO today) — surface to the LA, not a technical blocker.

---

## Source tiers + access dates (all accessed 2026-07-19)

- **T1:** GitHub Discussion #36484 (ours); arXiv 2508.06753v2; arXiv 2412.11053;
  intel.com Qwen3 article *(403 — see §1C / access-limited)*; OpenVINO docs/Medium
  first-party posts; OpenVINO Model Hub.
- **T2:** TechHara (Medium); Nikolay Falaleev (nikolasent.github.io); JoshCork
  (GitHub); Bibek Poudel (Medium); Neural-Hacker (HF community blog); OpenVINO DevRel
  "How to contribute" (Medium).
- **T3 (interest/demand only, never truth):** r/LocalLLaMA secondary rule aggregators
  (LaunchWake, OneUp, Intoru); OpenVINO issue #32306; general co-residency/KV-cache
  guidance blogs.

**Access failures honestly logged:** intel.com Qwen3 article — HTTP 403 (direct +
web.archive.org both failed); r/LocalLLaMA primary rules — tool-blocked on all Reddit
URL forms and the browser extension was not connected (primary-rules gap, §4A);
docs.openvino.ai/2026 contributing page — rendered nav-only. None were guessed; each is
marked at point of use.
