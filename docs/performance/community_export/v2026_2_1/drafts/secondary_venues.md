# Secondary / lighter-touch cross-link drafts

Tier-2 reach targets (the canonical home is the HF dataset + the OpenVINO "Show and tell" discussions; these are optional extra reach). Lighter than the primary set; post after the canonical home is up.

---

## A. Intel Community forum — OpenVINO board (community.intel.com)

Official, Intel-staffed board that hosts user benchmark/perf threads. Free Intel account → "Start a discussion." Frame as sharing results + inviting methodology critique (the board reads as Q&A/support, so lead with "sharing, feedback welcome," not a claim).

**Suggested title:** Lunar Lake / Arc 140V OpenVINO numbers (Qwen3 spec-decode, a 14B co-residency study, and a 2026.1.0→2026.2.1 A/B) — sharing + methodology feedback welcome

**Body:**

Hi all — I've been characterizing local LLM/VLM/image-gen inference on a Core Ultra 7 258V (Lunar Lake) with the Arc 140V iGPU via OpenVINO, and wanted to share the numbers here in case they're useful, and to get methodology critique from people closer to the runtime than I am (I'm a non-expert).

Stack: Arc 140V (Xe2), GPU driver 32.0.101.8826, Windows 11, OpenVINO GenAI 2026.1.0 / 2026.2.1 in-process (14B/8B/VLM) + OVMS 2026.2 (30B MoE). All on the iGPU; NPU idle (0 W, telemetry-confirmed). INT4 weights, greedy.

Highlights:
- **Spec-decode** (small 0.6B GPU draft): 14B 11.1 → 17.1 tok/s, 8B 19.8 → 27.4.
- **30B MoE (Qwen3-Coder-30B-A3B)**: 38.1 tok/s decode, but ≈480 pp prefill — the dense-vs-MoE mirror image.
- **Co-residency**: a resident 14B sharing the iGPU with a second model (SDXL or the VLM) — idle is ≈free, but concurrent generation saturates the GPU and the exhausted resource is **compute scheduling, not bandwidth or clock** (per-phase Level Zero + SoC Watch telemetry).
- **OpenVINO 2026.1.0 → 2026.2.1** (same driver/models/methodology): **cold prefill ≈28–36% faster** and **VLM TTFT ≈19% faster** (generation flat); and a GPU-vs-CPU **draft device** result (keep the draft on the GPU — a CPU draft is ≈13% slower at identical acceptance on this unified-memory part).

Full per-run data + methodology (CC-BY-4.0): https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake
Longer write-ups: https://github.com/openvinotoolkit/openvino/discussions/36604 and the 2026.2.1 follow-up.

This is an AI-assisted effort — real measurements on my hardware, but the harnesses/analysis/write-up were AI-assisted under my direction. I'd genuinely value any "you measured the wrong thing" feedback, especially on the co-residency contention probe and why a runtime bump would speed prefill but not decode.

---

## B. r/IntelArc (niche — Benchmark flair)

~45k members, established **Benchmark** flair; audience skews discrete-Arc/gaming, so iGPU LLM is slightly niche but on-topic. Read the sidebar self-promo rule before posting (rules page was fetch-blocked during research). Same 10%-rule discipline as r/LocalLLaMA: data in body, link in a top comment.

**Suggested title:** Arc 140V (Lunar Lake iGPU) as an LLM/diffusion accelerator via OpenVINO — Qwen3 spec-decode + running two models co-resident on the one iGPU (numbers)

**Body (short — point at the fuller r/LocalLLaMA / dataset for depth):**

The Arc 140V mostly shows up here for gaming, but it's a capable local-inference iGPU through OpenVINO, and I had a hard time finding numbers, so I measured some on a Core Ultra 7 258V (driver 32.0.101.8826, Windows 11, all on the iGPU, NPU idle):
- Qwen3-14B INT4 decode 11.1 → 17.1 tok/s (spec-decode off → on, small 0.6B GPU draft); 8B 19.8 → 27.4; 30B-A3B MoE 38.1.
- A **co-residency** study: a resident 14B sharing the iGPU + 27.3 GiB shared-memory window (87% override) with a second model — idle ≈free, but concurrent generation saturates the GPU; the bottleneck is compute scheduling, not bandwidth or clock (≈99% busy, no throttle, NPU 0 W).
- OpenVINO 2026.1.0 → 2026.2.1: cold prefill ≈28–36% faster, VLM TTFT ≈19% faster (decode flat).

One machine, posting for comparison + feedback. If you run an Arc (discrete or iGPU) through OpenVINO and see different numbers I'd love to compare. (AI-assisted: real measurements on my hardware, AI-assisted analysis/write-up.)

*(top comment: dataset https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake + the OpenVINO discussions.)*

---

## C. LocalScore (localscore.ai) — OPTIONAL good-faith correction only (NOT a submission)

LocalScore is CLI-only (llamafile / llama.cpp) with no Intel-GPU path — its `-g` flag is `auto|amd|apple|nvidia|disabled`, so on an Arc iGPU it falls back to CPU. **Do not submit OpenVINO numbers there** (any submission would be a CPU-fallback llamafile number that misrepresents the runtime). The existing 258V entry ([accelerator/720](https://www.localscore.ai/accelerator/720)) is CPU-class (≈4.3 gen tok/s on the 14B) AND mislabels the arch as "arrowlake-s" (the 258V is Lunar Lake).

The only worthwhile, honest action is a **GitHub issue** ([cjpais/LocalScore](https://github.com/cjpais/LocalScore)) flagging the arch mislabel — it still can't be made to report the iGPU, so frame it as a label fix, not a perf submission:

**Suggested issue title:** Accelerator 720 (Core Ultra 7 258V) is labeled arch "arrowlake-s" — it's Lunar Lake

**Body:** Small data-quality note: the accelerator at /accelerator/720 is a Core Ultra 7 258V, which is **Lunar Lake**, but it's labeled architecture "arrowlake-s". (Separately, FWIW, the result there looks CPU-class — which makes sense given LocalScore's `-g` options don't include an Intel/SYCL/Vulkan path, so on an Arc iGPU llamafile falls back to CPU. Not asking you to change that — just flagging the arch label.) Thanks for the project.
