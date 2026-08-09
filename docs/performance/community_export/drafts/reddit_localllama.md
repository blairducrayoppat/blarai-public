<!-- suggested flair: Resources -->
<!-- Reminder: r/LocalLLaMA's exact rules + the live flair list still need ONE human-browser
     check before posting (Reddit blocks automated readers), so "Resources" is provisional. -->

**Suggested Reddit title (paste into the title field, not the body):**
Qwen3-14B INT4 + a second model co-resident on a Lunar Lake iGPU (Arc 140V, 32 GB shared) — OpenVINO single-model + co-residency numbers (N=3)

---

**Hardware:** Intel Core Ultra 7 258V (Lunar Lake), integrated Arc 140V (Xe2) iGPU, 32 GB shared LPDDR5X-8533 (31.323 GiB effective shared budget, ≈136 GB/s theoretical), with the Intel Graphics Software "Shared GPU Memory" override set to **87%** → a **27.3 GiB iGPU window** into the pool (the enabling config — the default smaller window won't hold both models, so reproducers must set it). GPU driver 32.0.101.8826, Windows 11. Everything below runs on the iGPU through OpenVINO; the NPU sits idle the whole time (0 W, confirmed by telemetry).

I'm a non-expert just trying to characterize what this one laptop can actually do. Two things were hard to find numbers on elsewhere, so I measured them and figured I'd share:

1. the usual single-model decode / prefill / TTFT for a few Qwen3 sizes, including speculative decoding on vs off; and
2. what it costs to keep a **Qwen3-14B INT4 resident** while a **second model** — SDXL image generation, or a Qwen3-VL-8B vision model — shares the *same iGPU and the same shared RAM*.

This is a single machine, N=3 on the co-residency runs. I'm posting it for comparison and, honestly, for the methodology feedback — I'd like to hear what I got wrong and what's worth measuring next (specific asks at the bottom).

**To be upfront, this is AI-assisted:** the numbers are real, first-hand measurements on my own hardware (Arc 140V via OpenVINO), reproducible from the methodology below. The harnesses, analysis, and write-up were AI-drafted under my direction, but I've checked every number and take responsibility for it. Corrections welcome.

## Single-model (each model benchmarked alone)

| Model | Params | Config | Decode tok/s (median) | TTFT (ms) | Prefill tok/s |
|---|---|---|---|---|---|
| Qwen3-14B INT4 | 14B | spec-decode off | 11.1 | 466 | 1959 |
| Qwen3-14B INT4 | 14B | spec-decode on † | 17.1 | 470 | config-independent ‡ |
| Qwen3-8B INT4 | 8B | spec-decode off | 19.8 | 264 | 1968 |
| Qwen3-8B INT4 | 8B | spec-decode on † | 27.4 | 313 | config-independent ‡ |
| Qwen3-Coder-30B-A3B INT4 (MoE, ≈3B active) | 30B | single-stream | 38.1 | 214 | 480 |

† spec-decode draft = Qwen3-0.6B (pruned to 6 layers, INT8) running on the GPU.
‡ Prefill is a property of the model + runtime, not the decode config; the spec-on single-token prefill probe reads artificially low as a backend artifact, so I cite the spec-off rate (≈1959 / ≈1968 tok/s). Runtimes: the 14B/8B are OpenVINO GenAI 2026.1.0 in-process; the 30B is OVMS 2026.2 with continuous batching — different OpenVINO versions, so each row states its own.

A few notes:

- Speculative decoding (the small Qwen3-0.6B draft on the GPU) gives **≈1.5×** on the 14B (11.1 → 17.1 tok/s) and **≈1.4×** on the 8B (19.8 → 27.4).
- The MoE is the mirror image of the dense models: **fastest decode and TTFT** (38 tok/s, 214 ms) but **slowest prefill** (≈480 tok/s vs ≈1960 for the dense 14B/8B). It activates only ≈3B params per decode step, but still routes every prompt token through all experts at prefill — so decode is cheap and prefill is dear.
- I'm reporting medians; means run a bit lower in places (8B spec-off median 19.8 vs mean 16.2), so there's real run-to-run spread. Per-run data and mean/P95 are in the dataset.

## Co-residency: 14B resident, a second model sharing the iGPU

The question I was after: hold a Qwen3-14B (spec-decode on) resident, then load a second model and measure the 14B in three states — **baseline** (alone), **idle** (partner loaded but not generating), and **contention** (partner generating continuously while the 14B runs back-to-back for a fixed 15 s window). Mean over N=3.

**Fit + the 14B's retained throughput**

| Second model (generating) | Size (GiB) | Peak co-resident (GiB) | Headroom vs pool (GiB) | 14B baseline | 14B idle | 14B contention | Retained |
|---|---|---|---|---|---|---|---|
| SDXL photoreal finetune (RealVisXL V5.0) INT8, 1024², 30-step | 5.45 | 25.91 | 5.41 | 19.82 | 19.89 | 0.22 | 1.1% |
| SDXL base 1.0 INT8, 1024², 30-step | 5.59 | 26.13 | 5.19 | 19.81 | 19.60 | 0.19 | 1.0% |
| SDXL base 1.0 + style LoRA INT8, 1024², 30-step † | 5.77 | 27.59 | 3.73 | 19.46 | 19.39 | 3.27 | 16.8% |
| Qwen3-VL-8B-Instruct INT4 (vision) | 5.31 | 24.55 | 6.77 | 19.13 | 18.10 | 2.58 | 13.5% |

14B = Qwen3-14B INT4, spec-decode on; figures are decode tok/s, mean N=3; budget 31.323 GiB. Baseline σ < 0.3 tok/s across pairings (the resident 14B is stable). † This row is soft — see caveats.

**Telemetry during the contention phase** (mean N=3)

| Second model | GPU busy (idle → contention) | GPU freq (contention) | Throttle | Mem read GB/s (idle → contention) | iGPU rail (idle → contention) | NPU | SoC peak |
|---|---|---|---|---|---|---|---|
| SDXL photoreal | 90.8% → 99.9% | 1934 MHz | none | 72.5 → 23.6 | 8.6 → 11.6 W | 0.0 W | 81.0 °C |
| SDXL base 1.0 | 90.3% → 99.8% | 1939 MHz | none | 69.2 → 21.3 | 8.5 → 11.0 W | 0.0 W | 82.3 °C |
| SDXL base + LoRA | 82.2% → 98.8% | 1946 MHz | none | 57.3 → 47.0 | 8.4 → 8.6 W | 0.0 W | 80.0 °C |
| Qwen3-VL-8B (vision) | 88.2% → 98.7% | 1949 MHz | none | 66.7 → 61.3 | 8.1 → 8.3 W | 0.0 W | 80.0 °C |

What I take from it (for this machine only):

- **Everything fits — but it's tight, and worth being precise.** All four pairings completed without OOM within the **27.3 GiB iGPU window** (the 87% override). The peaks (24.5–27.6 GiB) are *total* unified-pool system-RAM — an upper bound on the GPU's own allocation, not the GPU slice alone — so the exact GPU-window headroom isn't isolated (the LoRA case's 27.6 GiB *total* peak even slightly exceeds 27.3, with the GPU slice below it and host memory making up the rest). What's clear: the 87% override is required — the default smaller window wouldn't hold both models.
- **Idle co-residence is near-free** for the SDXL partners (within run-to-run noise) and ≈5% for the VLM. Loading the second model barely touches the 14B until that model actually runs.
- **Concurrent generation saturates the GPU.** Under SDXL diffusion the 14B's decode collapses to **≈1% of baseline** — it can't even finish its prefill in the window (contention TTFT blows out to ≈13–15 s). Under the bandwidth-bound VLM and the LoRA case it holds **≈13–17%**.
- **The exhausted resource is compute scheduling — not clock, thermal, or bandwidth.** Across every pairing the GPU sits ≈99% busy, pinned near 1.95 GHz, **zero throttle**, ≈80–82 °C. What runs out is execution-unit occupancy, not headroom in frequency or temperature — the vector engines (`XVE_ACTIVE`) sit at only ≈20–31% even at ≈99% GPU-busy, so the GPU is occupied, not vector-saturated.
- **The memory-bandwidth signature splits by partner type.** Under compute-bound SDXL the aggregate read-rate *drops* (the 14B's bandwidth-bound decode can't get compute slots to even issue its reads); under the bandwidth-bound VLM it stays high.
- **NPU = 0 W in every phase of every run** — this is pure-GPU execution, no silent NPU offload.

One reconciliation in case you spot it: the co-residency baseline (≈19.8 tok/s) comes from the sustained back-to-back probe and reads a bit higher than the single-model spec-on median (17.1) up top — different probe; the retained-% is relative to this harness's own baseline.

## How I measured

- **Runtimes:** OpenVINO GenAI 2026.1.0 in-process for the 14B/8B; OpenVINO Model Server (OVMS) 2026.2 with continuous batching for the 30B MoE. The dense and MoE numbers are on different OpenVINO versions — each row says which.
- **Single-model:** 20 measured runs over a fixed 4-prompt set (+2 warm-up), 30 s inter-run cooldown, greedy decoding (temperature 0). Decode = output tokens / total latency; TTFT = time-to-first-token; prefill = input tokens / prefill time via a ≈970-token probe with `max_new_tokens=1` (the OVMS prefill probe is ≈421 tokens).
- **Co-residency:** the 14B is held resident; each partner is measured at baseline / idle / contention as described, N=3, with every run wrapped in Intel Unified Telemetry — Intel SoC Watch for iGPU-rail power, temperature, throttle reason, and NPU power; Level Zero for GPU frequency, GPU-busy %, and memory read/write rate (reported in GB/s — `GPU_MEMORY_BYTE_*_RATE` is defined as GB/s in Intel's OA metric set, per Mesa's `oa-lnl.xml` (`units="gbps"`); the telemetry tool just leaves the unit field as N/A).

## What I did not measure

- **One machine, one driver, one thermal environment, N=3.** This is a reference point, not a distribution — don't read it as a population estimate.
- **The LoRA ("cartoon") contention figure is soft.** Part of its milder slowdown is a CPU-side LoRA spin-up landing inside the fixed 15 s window — it has the highest variance of the set (contention σ ≈ 0.46 on a 3.27 mean). Read it as "the mildest SDXL pressure," not a steady-state diffusion number.
- **Spec-on prefill is a backend artifact** (the single-token probe still pays draft+target overhead) — cite the spec-off prefill rate.
- **Cross-model prefill is directional, not a controlled A/B** (different token counts and runtimes). The dense-vs-MoE prefill gap is far larger than those confounds, but it still isn't a clean A/B.
- **No co-resident cost is baked into the single-model table** — those were each run alone (and the 30B and 14B can't co-reside in the 27.3 GiB iGPU window anyway).
- **Level Zero per-phase timing is via a validated linear clock-remap** — the values are correct, but fine-grained phase alignment is approximate.

For context (not a comparison — I haven't run a controlled A/B): the same Arc 140V can also be driven through llama.cpp's SYCL backend, so OpenVINO is one path to this GPU, not the only one.

## Where I'd especially value a second opinion

This is my own measurement on my own single laptop, and I'm a non-expert — methodology critique is genuinely the point of posting. A few things I'm specifically unsure about:

- **The contention probe.** I quantify the resident model's retained throughput by running it back-to-back for a fixed 15 s window while the partner generates continuously. Is there a fairer or more standard way to measure "what a second model costs the first" on one shared GPU?
- **Steady-state vs spin-up.** The style-LoRA pairing's contention number is partly a fixed-window spin-up artifact; I'm planning to re-run with the partner warmed to steady state first. Is that the right fix, or is there a cleaner approach?
- **Prefill comparability.** My prefill probe uses different prompt lengths across models/runtimes. Is there a community-standard probe (a fixed `pp512`, say) I should align to so these compare cleanly across runtimes?
- **Replication.** One unit, one driver, N=3. If you have a Lunar Lake / Arc 140V machine and see different numbers, I'd really like to know.

And if any of these would actually be useful to you, say so and I'll try to add them: longer-context decode curves (these are short prompts), tokens-per-joule (I have the per-phase power), other model sizes/architectures on this iGPU, more co-residency pairings, or batched/concurrent throughput. Requests and corrections both welcome.

---

*Full per-run data + methodology (CC-BY-4.0): https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake*
