# Characterization (reference): two-model co-residency on an Intel Arc 140V (Lunar Lake) iGPU — a resident Qwen3-14B (INT4) holds near-free at idle but falls to ≈1% of baseline (19.8 → 0.2 tok/s) under a concurrent SDXL diffusion; the exhausted resource is GPU compute-scheduling, not memory bandwidth or clock. Methodology + numbers

**TL;DR.** On one Intel Core Ultra 7 258V (Lunar Lake) laptop with the integrated Arc 140V (Xe2) iGPU and 31.323 GiB of shared LPDDR5X, two models run within the iGPU's 27.3 GiB shared-memory window without out-of-memory (peak co-resident 24.5–27.6 GiB total unified-pool system-RAM across four pairings) and idle co-residence is near-free, but **concurrent generation saturates the GPU**. A resident Qwen3-14B INT4 (speculative decoding on, ≈19.8 tok/s alone) retains only **≈1%** of its decode throughput while an SDXL diffusion runs on the same iGPU, and **≈13–17%** under a bandwidth-bound vision model or a style-LoRA SDXL case. In every contention phase the GPU sits at ≈99% busy, pinned near **1.95 GHz with zero throttle reported** and the **NPU at 0 W** — so the bottleneck reads as **execution-unit occupancy / compute scheduling, not frequency, thermal, or memory bandwidth**. Underneath that sit the table-stakes single-model numbers (14B decode 11.1 → 17.1 tok/s spec off→on; 8B 19.8 → 27.4; 30B-A3B MoE 38.1) and a dense-vs-MoE prefill/decode mirror-image. *This is reference data shared for comparison and correction — not a bug report, and not a benchmark contest with any other runtime. I'd genuinely value methodology critique and suggestions for what to measure next; specific asks are at the end.*

**AI-assisted contribution, to be upfront:** the benchmark numbers here are real, first-hand measurements — run on my own hardware (the 258V / Arc 140V above) via OpenVINO, and reproducible from the methodology below. The harnesses, the analysis, and this write-up were drafted with an AI assistant working under my direction; I have reviewed and verified every number and claim and take full responsibility for them. The numbers come from measurement runs, not from a model. Methodology critique and corrections are especially welcome.

**Raw data.** Per-run measurements + the dataset card are published as a CC-BY-4.0 dataset → https://huggingface.co/datasets/blairducrayoppat/openvino-arc140v-lunarlake

*This continues a prior reference characterization on the same hardware: https://github.com/openvinotoolkit/openvino/discussions/36484*

---

## Setup

**Hardware**
- CPU / SoC: Intel Core Ultra 7 258V (Lunar Lake)
- GPU: Intel Arc 140V (Xe2, integrated); shared LPDDR5X-8533; ≈136 GB/s theoretical memory bandwidth; **31.323 GiB** effective shared budget
- Shared GPU memory: the Intel Graphics Software "Shared GPU Memory" override is set to **87%**, giving the iGPU a **27.3 GiB addressable window** into the unified pool (the figure shown in Intel Graphics Software and in Windows Task Manager → Performance → GPU). This is the enabling configuration for the co-residency results — the default, smaller window will not hold a resident 14B plus a second model; reproducers must set the same override.
- GPU driver: 32.0.101.8826
- OS: Windows 11

**Software**
- OpenVINO GenAI **2026.1.0** — in-process, for the 14B and 8B (including speculative decoding)
- OpenVINO Model Server (**OVMS**) **2026.2** — for the 30B MoE (continuous batching)
- The dense 14B/8B and the 30B MoE numbers are therefore on **different OpenVINO versions**; each results row states its own runtime.

**Models** (all weights quantized; all inference on the iGPU)
- Qwen3-14B INT4, Qwen3-8B INT4 — dense
- Qwen3-Coder-30B-A3B INT4 — Mixture-of-Experts, ≈3B active params per token
- Qwen3-VL-8B-Instruct INT4 — vision
- SDXL-class INT8 image models: RealVisXL V5.0, SDXL base 1.0, and SDXL base 1.0 + a style LoRA (all 1024×1024, 30-step)
- Speculative-decoding draft: Qwen3-0.6B (a pruned-6-layer INT8 build), also on the GPU

**Method**
- *Single-model.* Each model benchmarked alone — 5 measured runs + 2 warm-up over a fixed 4-prompt set (20 measured generations per row), a 30 s inter-run cooldown for thermal fairness, greedy decoding (temperature 0). Generation tok/s = output tokens / total latency; TTFT = time-to-first-token (a latency); prefill (pp) = input tokens / prefill time via a fixed ≈450–970-token probe with `max_new_tokens=1`.
- *Co-residency.* A Qwen3-14B (spec-decode on) is held resident; then for each partner model the full 14B suite (gen tok/s, prefill, TTFT) is measured in three states — **baseline** (14B alone), **idle** (partner loaded but not generating), and **contention** (partner generating continuously while the 14B runs back-to-back for a fixed 15 s window, a sustained probe to remove one-shot overlap-timing noise). N=3 per pairing; the tables report the mean (the dataset holds every run and the per-row standard deviations).
- *Telemetry.* Each co-residency run is wrapped in **Intel Unified Telemetry** (`ut.exe`) — **Intel SoC Watch** for energy→power (averaged as total mJ / total ms; peaks taken over 1 s windows to avoid sub-millisecond glitches), SoC/CPU temperature, throttle reason, and NPU power; **Level Zero** for GPU core frequency, GPU-busy %, and memory read/write rate. Samples are segmented into phases by wall-clock boundaries the harness emits.

---

## Results

All numbers are scoped to the single machine, driver, runtime, and models above — a reference point, not a population estimate.

### 1. Two-model co-residency on the same iGPU (the novel part)

**Memory fit** — every pairing completed without out-of-memory within the iGPU's **27.3 GiB shared-memory window** (the 87% override). The peaks (24.5–27.6 GiB) are *total* unified-pool system-RAM — an upper bound on the iGPU's own allocation, not the GPU slice alone — so the exact headroom against the 27.3 GiB window isn't isolated; what is clear is that the override is required and the heavy pairings push total use into the high-20s GiB (the resident Qwen3-14B INT4 spec-on plus the partner).

| Partner (alongside resident Qwen3-14B INT4, spec-on) | Partner resident (GiB) | Peak co-resident (GiB) | Headroom vs 31.3 GiB pool |
|---|---|---|---|
| RealVisXL V5.0 INT8 (SDXL, 1024², 30-step) | 5.45 | 25.91 | 5.41 |
| SDXL base 1.0 INT8 (1024², 30-step) | 5.59 | 26.13 | 5.19 |
| SDXL base 1.0 INT8 + style LoRA (1024², 30-step) | 5.77 | 27.59 | 3.73 |
| Qwen3-VL-8B-Instruct INT4 (vision) | 5.31 | 24.55 | 6.77 |

The +style-LoRA case is the tightest — its 27.59 GiB *total system-RAM* peak even slightly exceeds the 27.3 GiB iGPU window, which (since the run completed without OOM) means its GPU-side slice stayed under the window while host-side memory makes up the difference. (The headroom column above is against the 31.323 GiB *total pool*, not the GPU window.)

**Resident 14B throughput across states** (mean over N=3; ± = standard deviation):

| Partner | Baseline gen tok/s | Idle gen tok/s | Contention gen tok/s | Retained % | Contention TTFT (ms) |
|---|---|---|---|---|---|
| RealVisXL V5.0 (SDXL) | 19.82 ±0.229 | 19.89 | 0.22 ±0.012 | 1.1 | 13648.9 |
| SDXL base 1.0 | 19.81 ±0.123 | 19.60 | 0.19 ±0.021 | 1.0 | 14909.3 |
| SDXL base 1.0 + style LoRA | 19.46 ±0.269 | 19.39 | 3.27 ±0.46 | 16.8 | 867.4 |
| Qwen3-VL-8B-Instruct | 19.13 ±0.186 | 18.10 | 2.58 ±0.093 | 13.5 | 1080.0 |

Idle co-residence is effectively free for the SDXL partners (baseline vs idle within run-to-run noise) and a consistent ≈5% for the vision model (18.10 vs 19.13 tok/s). Under *concurrent* generation the picture splits sharply by partner type: the two plain SDXL diffusions drive the resident 14B to ≈1% retained (0.22 / 0.19 tok/s) — the 14B cannot even finish its prefill inside the window, hence the ≈13.6–14.9 s contention TTFT — while the bandwidth-bound vision model and the +style-LoRA SDXL case are milder at ≈13–17% retained. (The co-residency baseline ≈19.8 tok/s comes from this harness's sustained back-to-back probe and reads a little higher than the single-model spec-on median of 17.07 tok/s in §2 — a different probe; the retained-% figures are relative to this harness's own baseline.)

**Per-phase GPU telemetry** (Intel UT; idle vs contention phase, mean over N=3):

| Partner | GPU busy idle % | GPU busy contention % | GPU freq contention (MHz) | Throttle (max) | Mem read idle (GB/s) | Mem read contention (GB/s) | iGPU rail idle (W) | iGPU rail contention (W) | NPU (W) | SoC peak (°C) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| RealVisXL V5.0 (SDXL) | 90.8 | 99.9 | 1933.7 | 0.0 | 72.5 | 23.6 | 8.59 | 11.61 | 0.0 | 81.0 |
| SDXL base 1.0 | 90.3 | 99.8 | 1939.1 | 0.0 | 69.2 | 21.3 | 8.53 | 11.00 | 0.0 | 82.3 |
| SDXL base 1.0 + style LoRA | 82.2 | 98.8 | 1946.0 | 0.0 | 57.3 | 47.0 | 8.38 | 8.61 | 0.0 | 80.0 |
| Qwen3-VL-8B-Instruct | 88.2 | 98.7 | 1948.8 | 0.0 | 66.7 | 61.3 | 8.10 | 8.30 | 0.0 | 80.0 |

*Units note (memory bandwidth).* The memory-bandwidth metric (`GPU_MEMORY_BYTE_*_RATE`) is in GB/s — Intel's OA metric definition for Lunar Lake declares it `units="gbps"` (the raw byte counter divided by GPU time), per Mesa's `oa-lnl.xml`; the capture tool reports the unit as N/A, but the definition is explicit. The ≈108 GB/s peak in the raw per-run data is ≈79% of the 136 GB/s LPDDR5X ceiling.

Across every pairing the GPU goes to ≈99% busy under contention and stays pinned near **1.95 GHz with zero throttle reported**, the **NPU at 0 W**, SoC peak 80–82°C. With clock flat, nothing throttling, and the NPU idle, the resident model's starvation reads as **execution-unit occupancy / compute scheduling**, not frequency, thermal, or bandwidth. The raw vector-engine counter supports this: `XVE_ACTIVE` sits at only ≈20–31% under contention (photoreal 30.8%, illustration 27.7%, cartoon 21.5%, VLM 20.0%) even as GPU-busy hits ≈99% — the GPU is occupied, not vector-compute-saturated, so what is scarce is scheduling slots rather than raw vector throughput. The memory-bandwidth signature is consistent with that reading: under the compute-bound SDXL partners the aggregate read-rate *falls* under contention (e.g. 72.5 → 23.6 GB/s — the 14B's bandwidth-bound decode can't win compute slots to issue its reads), whereas the bandwidth-bound vision model keeps it high (66.7 → 61.3). The iGPU rail also draws *more* under the plain SDXL partners (≈8.5 → 11.6 W) while the 14B still starves — consistent with the diffusion monopolizing the EU scheduler rather than the link or the clock.

### 2. Single-model decode, prefill, and TTFT (table-stakes, with the MoE and spec-decode shapes called out)

| Model | Params | Runtime | Config | Gen median tok/s | Gen mean | Gen P95 | TTFT median (ms) | Prefill tok/s |
|---|---|---|---|---|---|---|---|---|
| Qwen3-14B | 14B | OV GenAI 2026.1.0 | spec-decode off | 11.13 | 10.08 | 11.89 | 466.3 | 1959.5 |
| Qwen3-14B | 14B | OV GenAI 2026.1.0 | spec-decode on † | 17.07 | 16.05 | 21.47 | 470.5 | 1308.4 \* |
| Qwen3-8B | 8B | OV GenAI 2026.1.0 | spec-decode off | 19.79 | 16.24 | 21.12 | 264.3 | 1967.8 |
| Qwen3-8B | 8B | OV GenAI 2026.1.0 | spec-decode on † | 27.37 | 21.89 | 29.73 | 313.1 | 1748.1 \* |
| Qwen3-Coder-30B-A3B (MoE, ≈3B active) | 30B | OVMS 2026.2 (cont. batching) | single-stream | 38.06 | 34.92 | 38.79 | 213.8 | 480.1 |

All models INT4; all rows = 20 measured generations + 2 warm-up over a fixed 4-prompt set, greedy/temperature 0, on the iGPU. † spec-decode draft = Qwen3-0.6B pruned-6-layer INT8, also on the GPU. \* spec-on prefill is a backend artifact (a single-token probe still pays draft+target overhead under speculative continuous batching); prefill is config-independent, so cite the **spec-off** prefill (≈1960 tok/s) as the rate.

**MoE profile.** The Qwen3-Coder-30B-A3B MoE (≈3B active params per token) has the **fastest decode and lowest TTFT** of the set — 38.06 tok/s, 213.8 ms — but the **slowest prefill** (480.1 tok/s vs ≈1960 for the dense 14B/8B). It activates only ≈3B params per decode step, yet routes every prompt token through the full expert set at prefill, so it pays roughly full-≈30B compute on the prompt. This dense-vs-MoE prefill/decode mirror-image is the most transferable shape here. (Measured on OVMS 2026.2 / continuous batching, vs OV GenAI 2026.1.0 in-process for the dense pair — see Caveats on the cross-runtime prefill comparison.)

**Speculative decoding.** The Qwen3-0.6B (pruned-6-layer INT8) GPU draft lifts decode median ≈1.5× on the 14B (11.13 → 17.07 tok/s) and ≈1.4× on the 8B (19.79 → 27.37), at near-unchanged 14B TTFT (466 → 471 ms) and a modest 8B TTFT rise (264 → 313 ms, ≈+19%). Mean and P95 are included so the run-to-run spread is visible alongside the median.

---

## Caveats and what I did not measure

- **Single machine, N=3.** One unit, one driver, one thermal environment. Not a fleet and not a distribution — a reference point, not a population estimate.
- **The +style-LoRA contention figure is soft.** Its milder slowdown partly reflects a style-LoRA CPU-side spin-up landing inside the fixed 15 s window (hence its higher variance, ±0.46). Read it as "the mildest SDXL pressure," not a steady-state diffusion number.
- **Level Zero per-phase timing uses a validated linear clock-remap.** The driver flags a timestamp-units uncertainty; the values are correct, but fine-grained phase alignment is approximate.
- **Speculative-decoding prefill is a backend artifact.** The spec-on prefill probe reads low because a single-token probe still pays draft+target overhead; prefill is config-independent, so the spec-off prefill (≈1960 tok/s) is the rate to cite.
- **Cross-model prefill is directional, not a controlled A/B.** The in-process probe is over ≈970 formatted tokens; the OVMS probe over ≈421 bare tokens; the runtimes differ. Each is internally valid, and the dense-vs-MoE prefill gap is far larger than those confounds — but it is not a like-for-like prefill comparison.
- **No co-resident cost in the single-model table.** Those models were each benchmarked alone (the 30B and the 14B cannot co-reside within the 27.3 GiB iGPU window).

---

## Feedback I'd especially value

I'm a non-expert measuring carefully on one machine, so methodology critique is the most useful thing anyone can offer. The specific places I'd most like to be checked:

- **Is a fixed-window, back-to-back probe a fair way to measure a resident model's *retained* throughput on a shared GPU?** The contention numbers depend on that design choice; I'd welcome a better-justified one.
- **Is warming the partner to steady state the right fix for the +style-LoRA spin-up confound?** That CPU-side spin-up landed inside the fixed 15 s window; pre-warming is my planned fix, but I'm not sure it's the cleanest.
- **Prefill-probe comparability.** My prefill rate is a fixed ≈450–970-token `max_new_tokens=1` probe. How does that line up with a community standard such as `pp512`, so these numbers are comparable to others'?
- **Replication on other Lunar Lake units.** This is N=3 on a single machine; a second unit or a different driver would show how much of this is the part versus the silicon.

## What would be useful to measure next?

Open to suggestions — current candidates, roughly in order of how often they seem to come up:

- Longer-context decode curves (throughput vs sequence length).
- Tokens-per-joule (per-phase power is already captured, so this is mostly a reporting step).
- Other models / architectures.
- More co-residency pairings.
- Batched throughput.

If one of these would be more useful to you than the others — or there's an obvious omission — please say so.

Thanks for reading; corrections, replications on other Lunar Lake units, and "you measured the wrong thing" are all genuinely welcome.
