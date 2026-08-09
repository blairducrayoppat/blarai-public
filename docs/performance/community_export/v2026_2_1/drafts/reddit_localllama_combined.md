<!-- suggested flair: Resources -->
<!-- Posting structure per r/LocalLLaMA's 10% self-promo norm: keep the BODY pure data;
     put the dataset + discussion LINKS in a TOP COMMENT (block at the bottom of this file),
     not in the post body. ONE human-browser check of the live rules + flair list before
     posting (Reddit blocks automated readers), and confirm the posting account has some
     karma/age (AutoMod may hold a brand-new account). -->

**Suggested title (hardware-first, plain — paste into the title field, not the body):**
OpenVINO on an Intel Lunar Lake iGPU (Core Ultra 7 258V / Arc 140V): Qwen3 spec-decode + a 14B co-residency study + a 2026.1.0→2026.2.1 version A/B (numbers + reproducible dataset)

---

**Hardware:** Intel Core Ultra 7 258V (Lunar Lake), integrated Arc 140V (Xe2) iGPU, 32 GB shared LPDDR5X-8533 (31.323 GiB effective, ≈136 GB/s theoretical), Intel Graphics Software "Shared GPU Memory" override at **87%** → a **27.3 GiB iGPU window** (the enabling config — the default smaller window won't hold both models, so reproducers must set it). GPU driver 32.0.101.8826, Windows 11. Everything runs on the iGPU through OpenVINO; the NPU sits idle the whole time (0 W, telemetry-confirmed).

I'm a non-expert trying to characterize what this one laptop actually does. A few things were hard to find numbers on elsewhere, so I measured them: single-model decode/prefill/TTFT for some Qwen3 sizes (incl. speculative decoding), what it costs to keep a 14B resident while a second model shares the iGPU, and a clean OpenVINO version A/B. Single machine; posting for comparison and methodology feedback (specific asks at the end).

## Single-model (each benchmarked alone)

| Model | Config | Decode tok/s (median) | TTFT (ms) | Cold prefill tok/s (pp@512) |
|---|---|---|---|---|
| Qwen3-14B INT4 | spec-decode off | 11.1 | 466 | 595 |
| Qwen3-14B INT4 | spec-decode on † | 17.1 | 470 | config-independent ‡ |
| Qwen3-8B INT4 | spec-decode off | 19.8 | 264 | 1086 |
| Qwen3-8B INT4 | spec-decode on † | 27.4 | 313 | config-independent ‡ |
| Qwen3-Coder-30B-A3B INT4 (MoE, ≈3B active) | single-stream | 38.1 | 214 | 480 (@421-tok) |

† draft = Qwen3-0.6B (pruned to 6 layers, INT8) on the GPU. ‡ Prefill is a model+runtime property, not a decode-config one; the spec-on single-token probe reads artificially low (backend artifact). **Prefill here is the *cold* rate** (dedicated harness, prefix-caching off) — these are 2026.1.0 numbers; on 2026.2.1 cold prefill is faster (14B pp@512 761, 8B 1477). Heads-up if you compare against my published dataset: its `single_model` table shows ≈1960 tok/s, but that probe is *prefix-cache-warm* (repeated prompts hit the KV cache) — an upper bound, not a cold rate. Runtimes: 14B/8B = OpenVINO GenAI 2026.1.0 in-process; 30B = OVMS 2026.2 (continuous batching).

- Spec decoding: **≈1.5×** on the 14B, **≈1.4×** on the 8B.
- The MoE is the mirror image of the dense models: **fastest decode + TTFT, slowest cold prefill** (≈480 vs ≈595–760 cold for the dense models) — ≈3B active params per decode step, but every prompt token routes through all experts at prefill. (The gap looks ≈4× if you use the dense models' *warm* ≈1960 number; cold-vs-cold it's ≈1.3–1.6×.)

## Co-residency: 14B resident, a second model sharing the iGPU (N=3)

Hold a Qwen3-14B (spec-on) resident, load a second model, measure the 14B at **baseline** (alone), **idle** (partner loaded, not generating), and **contention** (partner generating continuously, 14B back-to-back in a fixed 15 s window). Mean over N=3.

| Second model (generating) | Peak co-resident (GiB) | 14B baseline | 14B idle | 14B contention | Retained |
|---|---|---|---|---|---|
| SDXL photoreal (RealVisXL V5.0) INT8, 1024², 30-step | 25.91 | 19.82 | 19.89 | 0.22 | 1.1% |
| SDXL base 1.0 INT8, 1024², 30-step | 26.13 | 19.81 | 19.60 | 0.19 | 1.0% |
| SDXL base 1.0 + style LoRA, 1024², 30-step † | 27.59 | 19.46 | 19.39 | 3.27 | 16.8% |
| Qwen3-VL-8B-Instruct INT4 (vision) | 24.55 | 19.13 | 18.10 | 2.58 | 13.5% |

14B decode tok/s, mean N=3; budget 31.323 GiB. † soft — see caveats. (SDXL partners: photoreal = RealVisXL V5.0 `SG161222/RealVisXL_V5.0`, base = SDXL base 1.0 `stabilityai/stable-diffusion-xl-base-1.0`; identities confirmed from the converted models' metadata.)

**Telemetry during contention** (mean N=3): GPU-busy goes 88–91% → **≈99%**, core clock pinned ≈1.93–1.95 GHz, **zero throttle**, SoC 80–82 °C, **NPU 0 W**. Memory-read rate *drops* under SDXL (e.g. 72.5 → 23.6 GB/s) but stays high under the VLM (66.7 → 61.3). The vector engines (`XVE_ACTIVE`) sit at only ≈20–31% even at ≈99% GPU-busy.

What I take from it (this machine only):
- **Everything fits, but it's tight** — all four within the 27.3 GiB iGPU window (the 87% override is required). The 24.5–27.6 GiB peaks are *total* unified-pool system-RAM (an upper bound on the GPU slice, not the slice itself).
- **Idle co-residence is ≈free** (≈5% for the VLM); **concurrent generation saturates the GPU** — SDXL drives the 14B to **≈1%** (it can't finish prefill in the window; contention TTFT blows out to ≈13–15 s), the bandwidth-bound VLM/LoRA leave it **≈13–17%**.
- **The exhausted resource is compute scheduling — not clock, thermal, or bandwidth** (≈99% busy, no throttle, EUs only ≈20–31% active; the GPU is *occupied*, not vector-saturated).

## OpenVINO 2026.1.0 → 2026.2.1 (version A/B, same driver/models/methodology)

| | 2026.1.0 | 2026.2.1 |
|---|---|---|
| 14B cold prefill @512 tok | 595 | **761 (+28%)** |
| 8B cold prefill @512 tok | 1086 | **1477 (+36%)** |
| VLM TTFT (Qwen3-VL-8B) | 201 ms | **162 ms (≈19% faster)** |
| 14B decode (spec-on) | 17.07 | 17.20 (flat) |
| 8B decode (spec-on) | 27.37 | 27.09 (flat) |

**Cold prefill is ≈28–36% faster and the VLM TTFT ≈19% faster — token generation is unchanged.** (Mid-length prefill gains are larger but noisier; 512-token is the tight, solid point.) The win is in responsiveness — faster first token on long prompts, faster image understanding — not in steady-state decode, so a tokens/sec-only look would miss it. Two side findings on 2026.2.1: a **GPU vs CPU draft** comparison — GPU draft wins ≈13% at *identical* acceptance (on a unified-memory iGPU a CPU draft just adds CPU power/heat for less throughput); and a **30B MoE accuracy flag** (`MOE_USE_MICRO_GEMM_PREFILL=0`) that costs ≈19% gen / ≈28% TTFT for an accuracy benefit a 2.2K-context eval couldn't show. I also re-ran the co-residency on 2026.2.1 (N=1) and the pattern held.

## What I did not measure
One machine, one driver. Co-residency N=3 (the version A/B is N=5 gen / N=5 prefill, smaller for VLM/SDXL; the 2026.2.1 co-residency refresh is N=1). The LoRA contention figure is **soft** (a fixed-window spin-up artifact — read it as "mildest SDXL pressure"). Cross-model prefill is directional, not a like-for-like A/B. KV-cache as a *memory* lever I couldn't quantify from host-RAM sampling (the GPU pool is invisible to system "Available" on this unified-memory part) — reported as a null, not a saving. For neutral context (not a comparison — I haven't run a controlled cross-runtime A/B): the same Arc 140V can also be driven through llama.cpp's SYCL/Vulkan backends, so OpenVINO is one path to this GPU, not the only one.

*(Memory-bandwidth note: the capture tool leaves `GPU_MEMORY_BYTE_*_RATE` unit N/A; my reading of Intel's OA metric definition in Mesa's `oa-lnl.xml` — `units="gbps"`, equation = byte-counter ÷ GpuTime(ns), bytes-based with no ×8 — indicates GB/s, gigaBYTES not bits, so I treat it as GB/s; correction welcome if the OA spec intends otherwise.)*

## Where I'd value a second opinion
Methodology critique is the point of posting. Specifically: is a fixed-window back-to-back probe a fair way to measure a resident model's *retained* throughput on a shared GPU? Why would a runtime bump speed up *prefill* and *VLM TTFT* but not steady-state decode? How should I measure GPU-side KV-cache allocation on a unified-memory iGPU (host "Available" can't see it)? And replication — if you have a Lunar Lake / Arc 140V and see different numbers, I'd really like to know.

*AI-assisted, to be upfront: the numbers are real first-hand measurements on my own hardware (reproducible from the methodology above); the harnesses, analysis, and write-up were AI-drafted under my direction and I've checked every number and take responsibility for it. Corrections welcome.*

---

### TOP COMMENT (post separately, right after the thread goes up — keeps the body link-free per the 10% rule)

Full per-run data + methodology, CC-BY-4.0: https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake

Longer write-ups with the complete tables + telemetry (OpenVINO "Show and tell" discussions):
- Co-residency + single-model study: https://github.com/openvinotoolkit/openvino/discussions/36604
- 2026.1.0 → 2026.2.1 version A/B + draft-device + MoE flag: https://github.com/openvinotoolkit/openvino/discussions/36626
- Earlier NPU-vs-CPU draft-device study: https://github.com/openvinotoolkit/openvino/discussions/36484

Happy to run additional measurements if something specific would be useful — say so and I'll try to add it.
