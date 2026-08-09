# Characterization (reference): OpenVINO GenAI 2026.1.0 → 2026.2.1 on an Arc 140V (Lunar Lake) iGPU — *prefill* is ~28–36% faster and the VLM ~19% faster (controlled A/B), while token *generation* is unchanged; plus a GPU-vs-CPU draft-device result that completes an earlier NPU-draft study. Methodology + numbers

**TL;DR.** I re-measured my Lunar Lake (Core Ultra 7 258V / Arc 140V iGPU) inference stack across the OpenVINO GenAI **2026.1.0 → 2026.2.1** bump, holding hardware, GPU driver (32.0.101.8826), models, and methodology constant. **The useful finding: the bump makes prompt *processing* meaningfully faster — cold prefill ≈+28–36% at the tightest-measured 512-token point (larger but noisier at longer lengths), and the vision model's time-to-first-token ≈19% faster — under a controlled A/B.** That's where it helps in practice: faster first token on long prompts, faster image understanding. Token *generation* throughput, by contrast, is **unchanged** (Qwen3-14B spec-on ≈17.1 tok/s, 8B ≈27, flat both directions) — so a tokens/sec-only look would read the bump as a no-op and miss the gain. Two side studies: a **GPU-draft vs CPU-draft** speculative-decoding comparison (GPU draft wins by ≈13% at identical acceptance — completing the draft-device picture from an earlier NPU-draft post of mine), and a **30B MoE accuracy-flag** that costs ≈19% generation / ≈28% TTFT for an accuracy benefit a short eval could not demonstrate. The co-residency picture from my previous post reproduces on 2026.2.1 (a smaller, confirmatory N=1 pass). *This is reference data shared for comparison and correction — not a bug report, and not a benchmark contest with any runtime or version. Methodology critique and "you measured the wrong thing" are genuinely welcome; specific asks are at the end.*

**Raw data.** Per-config measurements + the dataset card are published (CC-BY-4.0), extended with these 2026.2.1 splits → https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake (new tables: `version_delta`, `draft_device`, `moe_flag`, `coresidency_2026_2_1`).

*This continues two prior reference characterizations on the same hardware: the co-residency + single-model study (https://github.com/openvinotoolkit/openvino/discussions/36604) and the NPU-vs-CPU draft-device study (https://github.com/openvinotoolkit/openvino/discussions/36484).*

---

## Setup

**Hardware**
- CPU / SoC: Intel Core Ultra 7 258V (Lunar Lake)
- GPU: Intel Arc 140V (Xe2, integrated); shared LPDDR5X-8533; ≈136 GB/s theoretical memory bandwidth; **31.323 GiB** effective shared budget
- GPU driver: **32.0.101.8826 — held constant across both runtime versions** (so the A/B isolates the runtime)
- OS: Windows 11

**Software — the A/B**
- **OpenVINO GenAI 2026.1.0** (`openvino 2026.1.0`, `openvino-tokenizers 2026.1.0.0`) vs **OpenVINO GenAI 2026.2.1** (`openvino 2026.2.1`, `openvino-tokenizers 2026.2.1.0`), in-process, for the 14B / 8B / VLM.
- The two versions were measured **back-to-back in separate Python virtual environments on the same machine**, same driver, same models, same harness — the only changed variable is the runtime. The production environment was never downgraded; the 2026.1.0 side was measured in a throwaway venv.
- The 30B MoE is served by **OpenVINO Model Server (OVMS) 2026.2** — **unchanged** across this campaign, so the 30B section is a flag A/B, not a version A/B.

**Models** (all weights quantized; all inference on the iGPU)
- Qwen3-14B INT4, Qwen3-8B INT4 — dense
- Qwen3-Coder-30B-A3B INT4 — Mixture-of-Experts, ≈3B active params per token (OVMS)
- Qwen3-VL-8B-Instruct INT4 — vision
- SDXL-class INT8 image models (co-residency partners), 1024×1024, 20-step — the photoreal partner is RealVisXL V5.0 (`SG161222/RealVisXL_V5.0`), the base/illustration partner is SDXL base 1.0 (`stabilityai/stable-diffusion-xl-base-1.0`), and the third adds a style LoRA on that base (identities confirmed from the converted models' `model_index.json` provenance)
- Speculative-decoding draft: Qwen3-0.6B (a pruned-6-layer INT8 build), on the GPU in production

**Method**
- *Generation A/B.* The committed baseline methodology, run identically on both versions: a fixed 4-prompt set, **5 measured runs + 2 warm-up** (20 measured generations per config), 30 s inter-run cooldown, greedy (temperature 0). Throughput = output tokens / total latency; TTFT = time-to-first-token.
- *Prefill A/B.* A dedicated multi-length prefill harness — fixed input lengths **512 / 2048 / 8192 tokens**, **N=5**, cold prefill (prefix-caching off), no draft. pp = input tokens / prefill time. This is far tighter than a single-shot prefill side-probe, so it is the trustworthy source for a prefill version delta; per-length std is reported below.
- *VLM A/B.* Fixed image + prompt; TTFT / TPOT / decode throughput median.
- *Draft device.* The 14B/8B spec-on run a second time with the draft pinned to the **CPU** vs the GPU; gen tok/s + a separate acceptance probe (accepted ÷ draft-proposed) on both.
- *Co-residency (N=1 refresh).* The 14B held resident (spec-on) while each partner runs, measured at baseline / partner-idle / sustained-contention, wrapped in Intel Unified Telemetry (SoC Watch + Level Zero). **N=1 per pairing here** — a confirmatory pass that the pattern survives the bump; the full **N=3 variance study is the 2026.1.0 dataset / discussion #36604.**

---

## Results

All numbers are scoped to the single machine, driver, runtime, and models above — a reference point, not a population estimate.

### 1. The version delta (the headline) — prefill and the VLM faster, generation flat

The bump speeds up the parts that gate *responsiveness* — prompt processing and the vision model — while leaving steady-state token generation unchanged. Leading with where it actually helps:

**Cold prefill (prompt processing) is faster on 2026.2.1** (median pp tok/s, N=5, no draft, prefix-cache off):

| Model | input length | 2026.1.0 | 2026.2.1 | change | variance note |
|---|---|---|---|---|---|
| Qwen3-14B INT4 | 512 | 595 | 761 | **+28%** | tight (std 57 → 9) — solid |
| Qwen3-14B INT4 | 2048 | 426 | 747 | +75% | noisier (std ~55 → 62) — directional |
| Qwen3-14B INT4 | 8192 | 277 | 388 | +40% | std 17 → 24 |
| Qwen3-8B INT4 | 512 | 1086 | 1477 | **+36%** | tight (std 157 → 9) — solid |
| Qwen3-8B INT4 | 2048 | 716 | 1106 | +54% | noisier (std 109 → 224) — directional |
| Qwen3-8B INT4 | 8192 | 592 | 627 | +6% | — |

Every length on both models is faster on 2026.2.1. I'd cite the **512-token points (+28% / +36%) as the solid claim** — their variance tightens dramatically on 2026.2.1 (std drops to single digits). The mid-range gains are larger but higher-variance, so I read those as directional. The practical effect: **faster first token on long prompts** (prefill is the time spent reading the prompt before the first output token).

**The vision model is faster too** (Qwen3-VL-8B-Instruct INT4, fixed image + prompt):

| metric | 2026.1.0 | 2026.2.1 | change |
|---|---|---|---|
| TTFT (median) | 201 ms | 162 ms | **≈19% faster** (solid) |
| TPOT (median) | 63 ms | 47 ms | ≈25% faster (directional) |
| decode throughput (median) | 15.9 tok/s | 21.1 tok/s | directional |
| load / compile | 7.8 s | 7.4 s | ≈ flat |

The 2026.1.0 run was noisier on TPOT than on TTFT, so I'd take **TTFT (≈19% faster) as the solid claim** and the TPOT/throughput gains as directional (consistent in sign, looser in magnitude).

**Token generation, by contrast, is unchanged** (median tok/s, greedy) — worth stating plainly so the gain above isn't mistaken for a generation speedup:

| Model | config | 2026.1.0 | 2026.2.1 | delta |
|---|---|---|---|---|
| Qwen3-14B INT4 | spec-decode off | 11.13 | 10.95 | flat (run-to-run noise) |
| Qwen3-14B INT4 | spec-decode on | 17.07 | 17.20 | flat |
| Qwen3-8B INT4 | spec-decode off | 19.79 | 19.62 | flat |
| Qwen3-8B INT4 | spec-decode on | 27.37 | 27.09 | flat |

So a tokens/sec-only comparison would read the bump as a no-op — the gain is real, it's just in prefill and the vision path rather than in steady-state decode.

### 2. Speculative-decoding draft device — GPU draft vs CPU draft (completing an earlier study)

Production runs the small 0.6B draft on the GPU (same device as the target). On a *discrete* GPU a CPU draft can be a win (it frees the GPU and overlaps draft/verify); on a *unified-memory* iGPU it pulls the same LPDDR5X and adds a CPU↔GPU sync per round, so it's genuinely empirical. Measured on 2026.2.1 (greedy, num_assistant_tokens = 3 — i.e. speculative length 3, same methodology as §1):

| target (GPU) + draft | gen median tok/s | acceptance (accepted ÷ draft-proposed) |
|---|---|---|
| Qwen3-14B, **GPU draft** | **17.20** | 45.0 % |
| Qwen3-14B, CPU draft | 14.88 (≈13% slower) | 45.1 % (identical) |
| Qwen3-8B, **GPU draft** | **27.09** | 48.3 % |
| Qwen3-8B, CPU draft | 23.48 (≈13% slower) | 48.1 % (identical) |

Acceptance is device-independent — as expected, the draft *device* doesn't change *which* tokens a greedy draft+target pair propose and accept, only how fast the draft produces them (a useful consistency check, and it validates the acceptance probe). Per-phase telemetry shows *why* the CPU draft is a lose-lose on this part: it shifts ≈1.5 W of draft compute off the iGPU rail onto the CPU/package (decode-phase package power 23.8 → 24.5 W, SoC temp 67.6 → 69.4 °C) for *less* throughput — the bottleneck was never GPU-compute availability, so offloading the draft just adds CPU power and heat. **On Arc 140V / Lunar Lake, keep the draft on the GPU.**

*How this completes [#36484](https://github.com/openvinotoolkit/openvino/discussions/36484):* there I compared a GPU target's draft on **none (GPU-only) / CPU / NPU** (a different draft build and harness — 128-token budget, single prompt) and found a CPU draft gave a **1.35× speedup over GPU-only** (16.5 vs 12.2 tok/s) while an NPU draft was a net slowdown (**0.55–0.74× of GPU-only**) — but that comparison had no GPU-draft arm. This campaign adds it: with the production draft and the standard methodology, **GPU draft > CPU draft** at identical acceptance. So the draft-device ordering on this unified-memory part is **GPU > CPU > NPU**. (The two studies use different draft builds — 0.6B INT4-symmetric there, 0.6B-pruned-6L INT8 here — and different harnesses, so don't cross-compare the absolute tok/s between posts; each is internally controlled. The *ordering* is the transferable finding.)

### 3. 30B MoE accuracy flag (`MOE_USE_MICRO_GEMM_PREFILL=0`) — a measured throughput cost

OVMS 2026.2 is unchanged across this campaign (the default arm reproduces my earlier 30B baseline: 38.6 vs 38.1 median). The `MOE_USE_MICRO_GEMM_PREFILL=0` flag, intended to recover MoE INT4 accuracy on long prompts, has a real price:

| Qwen3-Coder-30B-A3B (MoE) | gen median | TTFT median | coding eval (2.2K ctx) |
|---|---|---|---|
| flag ON (=0, accuracy mode) | 31.3 tok/s | 236 ms | 4/5 |
| flag OFF (default) | 38.6 tok/s | 184 ms | 4/5 |

The flag costs **≈19% generation throughput and ≈28% TTFT**, and on a defined, ground-truth coding eval at ≈2.2K-token context the two arms scored **identically (4/5, same answers)** — no measurable accuracy benefit *at that scale*. Its documented benefit is on much longer (repo-scale) prompts this eval did not reach, so this is **only a measurement of the cost** — the accuracy upside it's meant to buy needs an 8K–32K-token eval I haven't run (an open follow-up). Net: a quantified tradeoff worth knowing if you run Qwen3-MoE INT4 on an Intel GPU.

### 4. Co-residency on 2026.2.1 (N=1 confirmatory refresh)

The two-model co-residency finding from [#36604](https://github.com/openvinotoolkit/openvino/discussions/36604) reproduces on 2026.2.1 — a resident Qwen3-14B (spec-on) sharing the iGPU with a second model:

| Partner | 14B gen: baseline → idle → contention | retained | peak co-resident (GiB) |
|---|---|---|---|
| SDXL photoreal (RealVisXL V5.0) | 18.5 → 18.4 → 0.12 | **0.6%** | 27.05 |
| SDXL base 1.0 | 19.0 → 18.4 → 0.13 | 0.7% | 26.91 |
| SDXL base 1.0 + style LoRA | 17.7 → 19.0 → 2.48 | 14.0% | 28.82 |
| Qwen3-VL-8B-Instruct | 19.4 → 18.0 → 2.03 | 10.5% | 25.00 |

Same story as the N=3 study: **idle co-residence is ≈free**, but concurrent generation saturates the iGPU and starves the 14B — and the Level Zero telemetry again points at **compute scheduling, not bandwidth or clock**: under SDXL contention GPU-busy → ≈100% while GPU memory-read *rate falls* (66.2 → 18.9 GB/s for photoreal), with the core clock pinned ≈1.92 GHz and zero throttle; the bandwidth-bound VLM keeps read-rate higher (63 → 46) and leaves the 14B more headroom (10.5%). NPU = 0 W in every phase. **This is N=1 — a "does the pattern hold across the bump" check; the N=3 variance study with full per-phase telemetry is the 2026.1.0 dataset and #36604.** (The style-LoRA row again shows the soft, spin-up-influenced contention figure flagged in that post.) One methodology note for honesty: the SDXL partners here are **20-step** vs the N=3 study's **30-step** (a runtime-config change between campaigns) — it changes the partner's generation duration but not the ≈1% retained-throughput result, which is about compute monopolization rather than diffusion length.

### 5. Two negatives / nulls worth stating

- **KV-cache precision as a *memory* lever — could not be quantified by host-RAM sampling (honest null).** The GPU plugin accepts `u8`/`u4` KV cache. But sweeping {FP16, u8, u4} × {16K, 32K} context on the 14B, peak shared-RAM (In-Use = Total − Available) was **flat at ≈20.85 GB across every precision and both context lengths**. If the KV cache were visible to host-RAM sampling, 32K would be ≈2× the KV of 16K and u4 well below FP16 — it wasn't. That's the signature of a load-time GPU memory pool that system-"Available" sampling can't resolve on a unified-memory iGPU. So I have **no KV-memory saving to report** — it needs GPU-allocation-level instrumentation, not host Available. Reported as a limitation, not a fabricated number.
- **`min_p` (non-default sampling) — small, as expected.** Production is greedy (temp 0), so this is a what-if for `do_sample=True`. At temp 0.8, sweeping min_p {0, 0.05, 0.1}, the distinct-trigram ratio (higher = less repetition) rose 0.983 → 0.992 — a modest reduction in degenerate repetition at no latency cost. Small because the 14B at temp 0.8 already repeats little.

---

## A units note (memory bandwidth) — my reading of the source

The capture tool reports the Level Zero memory-bandwidth metric (`GPU_MEMORY_BYTE_READ_RATE` / `_WRITE_RATE`) with its unit as N/A, so I went to the OA (Observation Architecture) definition to pin it down. **My reading of that definition indicates GB/s (gigaBYTES per second):** for Lunar Lake it is declared `units="gbps"` and derived as the raw byte counter (`GPU_MEMORY_BYTE_READ`, `units="bytes"`) divided by `GpuTime` (`units="ns"`) — i.e. bytes ÷ nanoseconds = gigabytes/second (source: Intel's MDAPI metric set as carried in Mesa's `oa-lnl.xml`). On that reading the `gbps` token is **bytes-based, not bits** — the equation has no ×8 — so it is GB/s, not Gb/s. I'm treating bandwidth as GB/s on this basis (it firms up the "almost certainly GB/s" caveat from my earlier posts), but I'd welcome a correction if the OA spec intends otherwise.

## Caveats and what I did not measure

- **Single machine; modest N.** Generation N=5, prefill N=5, VLM / SDXL / min_p N=2–3, co-residency **N=1 this refresh** (the N=3 variance study is the 2026.1.0 split). One unit, one driver, one thermal environment — a reference point, not a distribution.
- **Prefill mid-range variance.** The 512-token points are tight (std < 10 on 2026.2.1); the 2048/8192 gains are larger but noisier (std up to ~220 on 8B-2048). Take the 512 points as the solid claim, the rest as directional.
- **VLM TPOT/throughput are directional** — the 2026.1.0 TPOT sample was noisier than its TTFT; only TTFT (≈19% faster) is the firm claim.
- **The 30B MoE accuracy flag's *benefit* is not demonstrated** — the eval was only ≈2.2K-token context; only the throughput *cost* is measured here.
- **The 2026.1.0 generation side is the committed baseline run under identical methodology, not a same-process back-to-back A/B** (the prefill and VLM sides *are* back-to-back venv A/Bs).
- **The style-LoRA co-residency contention figure is soft** (a fixed-window spin-up artifact, as in #36604); read it as "mildest SDXL pressure," not steady-state.
- **EAGLE-3** speculative-decoding conversion is blocked upstream on this stack — out of scope here.

## Feedback I'd especially value

I'm a non-expert measuring carefully on one machine, so methodology critique is the most useful thing anyone can offer:

- **Is a separate-venv, same-machine back-to-back the right way to A/B two OpenVINO versions?** I held HW/driver/models/harness constant and only swapped the runtime venv. Is there a confound I'm missing (e.g. tokenizer-version effects on prefill token counts)?
- **Why would a runtime bump speed up *prefill* and the *VLM TTFT* but not steady-state decode?** That split is the interesting part — if someone closer to the 2026.2.x changes can point at what changed (a prefill/attention kernel? a compile path?), I'd love to understand it rather than just report it.
- **The KV-cache memory question.** What's the right way to measure the GPU-side KV allocation on a unified-memory iGPU, since host "Available" can't see it? A Level Zero allocation query? `ze_memory`?
- **Replication on other Lunar Lake / Arc 140V units** — N is modest and it's one machine; different numbers on a second unit would be very useful to know.

## What would be useful to measure next?

Open to suggestions — current candidates: an 8K–32K-context eval to actually probe the MoE accuracy flag's intended regime; longer-context decode curves; GPU-allocation-level KV-cache memory measurement; a full N=3 2026.2.1 co-residency variance re-run; tokens-per-joule (per-phase power is already captured). If one of these is more useful to you than the others, say so.

Thanks for reading — corrections, replications on other Lunar Lake units, and "you measured the wrong thing" are all genuinely welcome.

---

*AI assistance, to be upfront: the benchmark numbers here are real, first-hand measurements — run on my own hardware (the 258V / Arc 140V above) via OpenVINO, and reproducible from the methodology above. The harnesses, the analysis, and this write-up were drafted with an AI assistant working under my direction; I have reviewed and verified every number against the on-disk result files and take full responsibility for them. The numbers come from measurement runs, not from a model — but please weigh the analysis and framing with that in mind, and corrections are especially welcome. Per the OpenVINO AI Usage Policy.*
