---
license: cc-by-4.0
language:
  - en
pretty_name: "OpenVINO local-inference on Intel Arc 140V (Lunar Lake) — LLM, MoE, VLM, image-gen, and a model co-residency study"
tags:
  - benchmark
  - performance
  - inference
  - openvino
  - intel
  - arc-140v
  - lunar-lake
  - igpu
  - xe2
  - llm
  - qwen3
  - speculative-decoding
  - mixture-of-experts
  - co-residency
  - telemetry
  - level-zero
  - ovms
  - tabular
task_categories:
  - text-generation
size_categories:
  - n<1K
annotations_creators:
  - other
configs:
  - config_name: single_model
    data_files: single_model.csv
  - config_name: coresidency
    data_files: coresidency.csv
---

# OpenVINO local-inference on an Intel Arc 140V (Lunar Lake) iGPU

Reference performance data for running local models on a single **Intel Core Ultra 7 258V
(Lunar Lake)** laptop with the integrated **Intel Arc 140V (Xe2)** GPU, via **OpenVINO**. All
inference runs on the iGPU; the NPU stays idle throughout, confirmed by the telemetry here.

This is **reference characterization** shared by a non-expert contributor — careful measurements
on one machine, offered so others can compare and correct, not a definitive benchmark. Every number
is scoped to the hardware, driver, runtime, and model stated here. **Feedback and corrections are
very welcome** — if something looks off or I've measured the wrong thing, please open a discussion.

**This is an AI-assisted contribution.** The benchmark measurements here are real, first-hand results —
captured on the contributor's own hardware (the Intel Arc 140V described below) via OpenVINO, and
reproducible from the methodology here. The analysis, the dataset packaging, and this card were drafted
with an AI assistant working under the contributor's direction. The contributor (a non-expert) owns the
goals, the hardware, and the decisions, has reviewed and verified every number and claim, and takes full
responsibility for them. The numbers come from measurement runs, not from a model — but please weigh the
analysis and framing with that in mind, and corrections are especially welcome.

## Key findings

- **Single-model decode (median tok/s):** 14B **11.1** (spec-off) → **17.1** (spec-on, ≈1.5×); 8B
  **19.8** → **27.4** (≈1.4×); 30B-A3B MoE **38.1**. Spec-decode uses the small Qwen3-0.6B draft on the
  GPU. The MoE has the **fastest decode and TTFT** (213 ms) but the **slowest prefill** (≈480 tok/s vs
  ≈1960 for the dense 14B/8B) — it activates only ≈3B params per decode step but routes every prompt
  token through all experts at prefill. This dense-vs-MoE mirror-image is the most useful shape here.
- **Co-residency fit:** all four pairings completed without out-of-memory, within both the **27.3 GiB
  iGPU window** (the 87% override) and the 31.323 GiB system pool. The reported peaks (24.5–27.6 GiB) are
  total unified-pool system-RAM (the harness reads system-Available as a proxy) — an upper bound on the
  iGPU's own allocation, not the GPU slice alone — so the exact headroom against the 27.3 GiB window
  isn't isolated here; what is clear is that the **87% override is required** (the default, smaller
  window would not hold a resident 14B plus a second model and its working set), and the heavy pairings
  push total use into the high-20s GiB (the style-LoRA case peaks at 27.6 GiB total, its tightest). The
  "Headroom vs pool" values elsewhere are measured against the 31.323 GiB total. Idle co-residence is
  effectively free for the SDXL partners (within run-to-run noise) and a consistent ≈5% for the VLM.
- **Co-residency under concurrent load:** the resident 14B's decode is throttled to **≈1%** of baseline
  by SDXL diffusion (compute-bound, monopolizes the execution-unit scheduler so completely the 14B
  can't finish even its prefill in the window), and to **≈13–17%** by the bandwidth-bound VLM and the
  LoRA case. Across every pairing the GPU goes to ≈99% busy and stays pinned near **1.95 GHz with zero
  throttle** — so the starvation is **occupancy/compute-scheduling, not frequency, thermal, or
  bandwidth**. The vector-engine counter supports this — `XVE_ACTIVE` is only ≈20–31% under contention
  (30.8 / 27.7 / 21.5 / 20.0% across the pairings) even at ≈99% GPU-busy, i.e. the GPU is occupied, not
  vector-compute-saturated. The memory-bandwidth signature splits by partner type: under compute-bound SDXL the
  aggregate read-rate *drops* (the 14B's bandwidth-bound decode can't get compute slots to issue its
  reads), while the bandwidth-bound VLM keeps it high.
- **NPU = 0 W in every phase of every run** — a repeated confirmation that this is pure-GPU execution.

## Files

| File | What it is |
|---|---|
| `single_model.csv` / `.jsonl` | One row per model × config: generation tok/s (median/mean/P95), prefill tok/s, TTFT, run counts. |
| `coresidency.csv` / `.jsonl` | One row per pairing: memory fit, the 14B's throughput at baseline/idle/contention, and per-phase GPU telemetry (busy %, freq, bandwidth, iGPU-rail power, NPU power, temperature), mean over N=3. |
| `raw/` | The unaggregated per-run JSON for every run (12 co-residency runs + the 3 single-model runs), so the aggregates can be checked and the variance seen. |

## Hardware and software

- **CPU / SoC:** Intel Core Ultra 7 258V (Lunar Lake)
- **GPU:** Intel Arc 140V (Xe2, integrated), shared LPDDR5X-8533, ≈136 GB/s theoretical memory bandwidth, **31.323 GiB** effective shared budget
- **Shared GPU memory:** the Intel Graphics Software "Shared GPU Memory" override is set to **87%**, giving the iGPU a **27.3 GiB addressable window** into the unified pool (the value shown in Intel Graphics Software and in Windows Task Manager → Performance → GPU). This is the **enabling configuration** for the co-residency results — the default, smaller window will not hold a resident 14B plus a second model, so reproducers must set the same override.
- **GPU driver:** 32.0.101.8826
- **OS:** Windows 11
- **Runtimes:** OpenVINO GenAI **2026.1.0** (in-process, for the 14B and 8B); OpenVINO Model Server (**OVMS**) **2026.2** (for the 30B MoE, continuous batching)
- **Models:** Qwen3-14B INT4, Qwen3-8B INT4, Qwen3-Coder-30B-A3B INT4 (MoE), Qwen3-VL-8B-Instruct INT4 (vision), and SDXL-class INT8 image models (RealVisXL V5.0 and SDXL base 1.0, ± a style LoRA). Speculative-decoding draft: Qwen3-0.6B (a pruned-6-layer INT8 build) on the GPU.

## Methodology

**Single-model (`single_model`).** Each model was benchmarked alone: 5 measured runs + 2 warm-up, a
30 s inter-run cooldown for thermal fairness, greedy decoding (temperature 0), over a fixed 4-prompt
set (so the `num_runs` column is 5 runs × 4 prompts = 20 measured generations per model/config).
Generation throughput = output tokens / total latency. **TTFT** = time-to-first-token (a
latency). **Prefill (pp)** = input tokens / prefill time, via a fixed ≈450–970-token probe with
`max_new_tokens=1`. The 14B/8B in-process numbers and the 30B OVMS numbers are on **different
OpenVINO versions** (2026.1.0 vs 2026.2) — each row states its own runtime.

**Co-residency (`coresidency`).** A Qwen3-14B (spec-decode on) is held resident, then for each partner
model the full 14B suite (gen tok/s, prefill, TTFT) is measured in three states: **baseline** (14B
alone), **idle** (partner loaded but not generating), and **contention** (partner generating
continuously while the 14B runs back-to-back for a fixed 15 s window — a sustained probe that removes
the overlap-timing noise of a one-shot measurement). N=3 repeats per pairing; the tables report the
mean (the `raw/` files hold every run, and the per-row standard deviations are included for the
headline throughput). The co-residency **baseline** of ≈19.8 tok/s comes from this sustained
back-to-back probe and reads a little higher than the single-model spec-on median of 17.07 tok/s in
the `single_model` table — a different probe; the retained-% figures are relative to this harness's
own baseline.

**Telemetry.** Each co-residency run is wrapped in **Intel Unified Telemetry** (`ut.exe`): **Intel SoC
Watch** for energy → power (averaged as total mJ / total ms; peaks taken over 1 s windows to avoid
sub-millisecond glitches), SoC/CPU temperature, throttle reason, and NPU power; **Level Zero** for GPU
core frequency, GPU-busy %, and memory read/write bandwidth. Samples are segmented into phases by
wall-clock boundaries the harness emits.

**Units note — memory bandwidth.** The Level Zero / OA memory-bandwidth metric
(`GPU_MEMORY_BYTE_READ_RATE` / `_WRITE_RATE`) is in **GB/s** (gigabytes/second). Intel's OA metric
definition for Lunar Lake declares it `units="gbps"` and derives it as the raw byte counter
(`GPU_MEMORY_BYTE_READ`, `units="bytes"`) divided by GPU time — bytes per nanosecond, i.e.
gigabytes/second. (Source: Intel's metric set as captured in Mesa's `oa-lnl.xml`.) The capture tool
reports this unit as N/A, but Intel's definition is explicit; the ≈108 GB/s peak here is ≈79% of the
136 GB/s LPDDR5X-8533 ceiling.

## What's hard to find elsewhere

Most "what can this laptop run" data is single-model tokens/second. The parts that are hard to find
elsewhere:

1. **Model co-residency cost.** What a resident Qwen3-14B (INT4, speculative decoding on) costs when a
   *second* model — SDXL image generation, or a Qwen3-VL-8B vision model — shares the **same iGPU and
   the same shared system RAM**. Every pairing runs within the iGPU's 27.3 GiB shared-memory window without out-of-memory (peak
   24.5–27.6 GiB total unified-pool system-RAM), idle co-residence is near-free, but **concurrent generation saturates the GPU**, and
   the exhausted resource is **compute scheduling — not memory bandwidth and not clock**.
2. **Per-phase GPU telemetry via Intel Unified Telemetry** (Intel SoC Watch + Level Zero): iGPU-rail
   power, GPU frequency, GPU-busy %, memory-bandwidth, and a **0 W NPU** confirming pure-GPU execution
   — not just wall-clock tokens/second.
3. **A Mixture-of-Experts (MoE) prefill/decode profile** — Qwen3-Coder-30B-A3B (≈3B active params) on
   this iGPU.
4. **Speculative-decoding numbers** for the 14B and 8B (draft model on the GPU), spec-off vs spec-on.

## Caveats and what I did not measure

- **Single machine, N=3.** One unit, one driver, one thermal environment. Not a fleet; not a
  distribution. Treat as a reference point, not a population estimate.
- **The cartoon pairing's contention figure is soft.** Its milder slowdown partly reflects a style-LoRA
  CPU-side spin-up landing inside the fixed 15 s window (hence its higher variance). Read it as "the
  mildest SDXL pressure," not a steady-state diffusion number.
- **Level Zero per-phase timing is via a validated linear clock-remap.** The driver flags a
  timestamp-units uncertainty; values are correct, fine-grained alignment is approximate.
- **Speculative-decoding prefill is a backend artifact.** The spec-on prefill probe reads low because a
  single-token probe still pays draft+target overhead; prefill is config-independent, so the **spec-off
  prefill (≈1960 tok/s) is the rate to cite**.
- **Cross-model prefill is directional, not a controlled A/B.** The in-process probe is over ≈970
  formatted tokens; the OVMS probe over ≈421 bare tokens; the runtimes differ. Each is internally
  valid; the dense-vs-MoE prefill gap is far larger than those confounds.
- **No co-resident cost is in `single_model`** — those models were each benchmarked alone (the 30B and
  the 14B cannot co-reside within the 27.3 GiB iGPU window).

## Feedback I'd especially value

I'm a non-expert sharing measurements, so methodology critique is genuinely wanted — please tell me
where this is wrong or could be sharper. A few specific things I'm unsure about:

- **The co-residency contention probe.** I measure the resident model's retained throughput by running
  it back-to-back for a fixed 15 s window while the partner generates continuously. Is there a more
  standard or fairer way to quantify "what a second model costs the first" on one shared GPU?
- **Steady-state vs spin-up.** The style-LoRA pairing's contention figure is partly a fixed-window
  spin-up artifact; I plan to re-run with the partner warmed to steady state first. Is that the right
  fix, or is there a cleaner approach?
- **Prefill comparability.** My prefill probe uses different prompt lengths across models/runtimes. Is
  there a community-standard prefill probe (e.g. a fixed `pp512`) I should align to so these compare
  cleanly across runtimes?
- **Replication.** This is one unit, one driver, N=3. If you have a Lunar Lake / Arc 140V machine and
  see different numbers, I'd really like to know.

## What would be useful to measure next?

If any of these would be valuable to you, say so and I'll try to add them: longer-context decode curves
(these are short prompts); tokens-per-joule (I have per-phase power); other model sizes or
architectures on this iGPU; additional co-residency pairings; or batched/concurrent throughput.
Requests and suggestions are welcome.

## Reproduce

The methodology is fully described above. The single-model harness is a fixed-prompt-set benchmark
(generation + a `max_new_tokens=1` prefill probe); the co-residency harness loads the 14B once and
measures it against each partner at baseline/idle/contention with Intel UT wrapping each run. The
`raw/` per-run files contain the exact configs, phase timestamps, and per-run numbers behind every
aggregate.

## License and citation

Released under **CC-BY-4.0**. If this is useful, attribution is appreciated:

> OpenVINO local-inference on Intel Arc 140V (Lunar Lake) — single-model, MoE, VLM, and a 14B
> co-residency study. Measured with OpenVINO GenAI 2026.1.0 / OVMS 2026.2, GPU driver 32.0.101.8826.

This is a single contributor's measurements on one laptop, shared in the spirit of the OpenVINO and
local-inference community. Corrections, replications on other Lunar Lake units, and methodology
critiques are all welcome.
