# 14B Co-Residency Study with Intel Unified Telemetry — How to Reproduce

This documents the **full, publishing-grade** co-residency measurement: what it
costs the always-resident Qwen3-14B (spec-on) to share the Arc 140V iGPU with a
second model (each image-gen style + the VLM), captured with Intel **Unified
Telemetry (UT)** for real GPU power / frequency / memory-bandwidth.

It exists because the quick first pass had three data-quality gaps (overlap-timing
noise in contention, thermal baseline drift, sub-millisecond power-peak glitches).
The hardened pipeline below fixes all three and runs **multiple repeats** for
variance. Future agents: run the one command in §3 to regenerate the whole dataset.

## 1. Prerequisites

- **Elevated (Administrator) shell** — UT's socwatch/level-zero drivers require it.
  Check: `([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)`
- **Intel UT tool** at the path in the **`INTEL_UT_HOME`** env var (set User-scope on this box),
  default `C:\Users\mrbla\tools\intel-ut\ut-tool-ext-v0.2.0-beta1.1` (`ut.exe`,
  `bin2perfetto.exe`; collectors socwatch + level-zero). Lunar Lake + Arc driver required.
  (Original archive kept at `~\Downloads\ut-tool-ext-v0.2.0-beta1.1.zip`.)
- **Models present** under `models/`: `qwen3-14b`, `qwen3-0.6b-pruned-6l`,
  `sdxl-uncensored`, `sdxl-illustration` (+ `lora/DD-vector-v2.safetensors`),
  `qwen3-vl-8b-instruct`. (gitignored — staged on the box only.)
- The GPU must be **free** (no OVMS / other resident model) — the 14B + a second
  model peak ~26-29 GiB against the 31.323 GiB ceiling.
- Run with **`LOCALAPPDATA` redirected** to a scratch dir (the harness can touch the
  real session store otherwise).

## 2. The pieces

| Script | Role |
|---|---|
| `scripts/benchmark_coresident.py` | The harness. Loads the 14B once (spec-on); per partner measures the full 14B suite (gen tok/s, pp, TTFT) at **baseline / partner-idle / contention**, memory fit, partner op time. **Sustained contention**: the 14B runs back-to-back for a fixed 15 s window while the partner generates *continuously* (kills the overlap-timing noise). Emits **wall-clock phase boundaries** (Unix s) for per-phase telemetry. `--partners`, `--out-tag`. |
| `scripts/extract_ut_metrics.py` | Streams `bin2perfetto -f console` over a `.socwatch.bin` **or** `.l0_gpu.bin`, segments samples into phases by Unix-epoch timestamp, aggregates per phase + whole-run. Energy (mJ) → avg W + **1 s windowed peak** (robust vs sub-ms glitches); instantaneous (freq/busy/bandwidth/temp) → avg/peak/min. Pass `--harness <harness.json>` to derive phases automatically. |
| `scripts/merge_coresident_hardened.py` | Aggregates **N repeats** per pairing → mean ± std (+ min/max/n) for every metric, per phase. |
| `scripts/run_coresident_ut_sweep.ps1` | Orchestrator: loops `partner × repeat`, wraps each in `ut.exe --enable socwatch,level-zero`, extracts per-phase after each, **cools down between runs**. (Drops `emon` — its stop-phase processing on large captures hangs UT finalization.) Resolves the tool via `INTEL_UT_HOME`; `-OutRoot` sets where the large `.bin` files go. |
| `scripts/capture_one.ps1` | **Foreground** single-run capture + extract (one tag). Use when the environment reaps background UT tasks — a foreground call completes within one invocation and can't be killed at a turn boundary. Extracts l0 with the remap inline. The 2026-06-28 vlm runs were captured this way. |
| `scripts/rextract_l0_remap.ps1` | Re-extract every already-captured l0 bin **per-phase** with `--remap-from` (the clock fix), e.g. after a sweep whose per-run extract predated the remap. |

## 3. Run the full collection

From an **elevated** PowerShell, repo root:

```powershell
# 1. The multi-sweep (4 partners x 3 repeats, ~60 min; run in background).
.\scripts\run_coresident_ut_sweep.ps1 -Partners photoreal,illustration,cartoon,vlm `
  -Repeats 3 -CooldownS 45 -OutRoot D:\bench\coresident
#    -> writes per-run harness JSONs to docs/performance/benchmark_coresident_<tag>_*.json
#       and per-phase metrics to <OutRoot>\ut_hardened\ut_<tag>.{socwatch,l0}.metrics.json

# 2. Aggregate across repeats into the publishing dataset.
.\.venv\Scripts\python.exe scripts\merge_coresident_hardened.py `
  --perf-dir docs\performance --ut-dir <scratch>\ut_hardened `
  --partners photoreal illustration cartoon vlm --repeats 3 `
  --out docs\performance\coresident_14b_pairings_hardened_<YYYY-MM-DD>.json
```

`<scratch>` = the session scratchpad. Each pairing run reloads the 14B (~20 s) so a
hang in one never strands the others; the `.bin` files are large (socwatch ~0.2-0.5
GB, l0_gpu ~0.7-1.9 GB per run) and live in scratch — they are **not** committed.

## 4. Metrics + caveats (read before citing)

- **Power**: socwatch energy (mJ/sample) → W. `avg_w` (total mJ / total ms) is the
  trustworthy figure; `peak_w_1s` is the max over 1 s windows. **Do not** use raw
  per-sample power — a handful of sub-ms samples produce spurious ~kW spikes.
- **GPU freq / busy / bandwidth**: from level-zero (`GPU.CoreFrequencyMHz`,
  `GPU.GPU_BUSY`, `GPU.GPU_MEMORY_BYTE_READ_RATE` / `_WRITE_RATE`, `GPU.XVE_ACTIVE`).
  The driver flags a **timestamp-units** uncertainty for level-zero (values correct;
  fine-grained time alignment approximate). `GPU_MEMORY_BYTE_*_RATE` unit is reported
  N/A — **likely GB/s** (peak ~108 vs the ~136 GB/s LPDDR5X ceiling) but UNCONFIRMED.
- **NPU**: `PMT-NPU-PWR` ~0 W everywhere confirms BlarAI is pure-GPU (ADR-011); the
  separate NPU is never used.
- **socwatch `ddr-bw` + `igfx-pstate`** are NOT exposed at any config level on this
  box — GPU bandwidth/frequency come from level-zero instead (above). System-wide
  DDR bandwidth via emon EDP is an untried follow-up.
- **Phases**: socwatch timestamps are Unix-epoch ns, so per-phase power segmentation
  is reliable. level-zero sample timestamps are on a *different* clock (the
  timestamp-units caveat — measured ~27.7 h offset from socwatch in-session), so
  `extract_ut_metrics.py --remap-from <socwatch.bin>` linearly anchors the l0 clock
  onto socwatch's Unix window from the same capture session, restoring per-phase l0
  segmentation. **Validated 2026-06-28**: remapped contention samples show the
  expected GPU-busy spike (idle ~90% → contention ~99%) and the freq/busy/bandwidth
  split is physically coherent. The runner now passes `--remap-from` automatically.
- **Background UT tasks are reaped in this environment — drive the capture in the
  foreground.** Confirmed 2026-06-28: the detached background sweep + its watcher were
  killed twice, together, mid-run at the turn boundary; the operator confirmed it was
  **not** user-initiated, and every *foreground* call completed untouched (including a
  4-minute parallel CPU load). So the foreground path is the **required method here,
  not a fallback**:
  - Capture one run per call with `capture_one.ps1` (each ~5 min, completes within a
    single invocation; extracts socwatch + remapped l0 inline).
  - If a multi-run call auto-backgrounds itself for length, **block-wait on it inline**
    (do not end the turn and gamble on it surviving).
  - Re-extract any already-captured bins per-phase with `rextract_l0_remap.ps1`.
  - Do **not** launch `run_coresident_ut_sweep.ps1` as a detached background job here;
    run it foreground, or drive `capture_one.ps1` one run at a time.
- **cartoon (LoRA) contention** is milder than plain SDXL and higher-variance: the
  DD-vector LoRA's CPU-side application leaves GPU scheduling gaps within the fixed
  15 s window, so the 14B retains slots (fast TTFT, more tokens). Read its contention
  figure as "mildest SDXL pressure," not a steady-state diffusion number.

## 5. What the dataset answers

For each pairing: does it fit in 31.323 GiB + headroom; the 14B's gen/pp/TTFT at
idle vs contention; iGPU rail power, GPU frequency, GPU-busy %, and memory bandwidth
idle vs contention; SoC/CPU temperature; NPU-idle confirmation — each as mean ± std
over the repeats. The headline: idle co-residence is ~free; concurrent generation
saturates the GPU (busy → ~100 %, bandwidth → near the LPDDR5X ceiling) and starves
the 14B — quantified, with the mechanism measured.
