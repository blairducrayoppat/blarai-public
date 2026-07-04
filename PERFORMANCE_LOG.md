# BlarAI Inference Performance Log

This file is the authoritative tracked log of BlarAI's local-model inference
performance. Every change that could affect throughput — speculative decoding
toggle, EAGLE3 integration, OpenVINO or driver upgrades, model swaps — must
produce a new dated entry here so improvements (and regressions) are visible
over time.

Long-term intent: accumulate a solid, reproducible dataset for potential
contribution to the OpenVINO / HuggingFace benchmarking community. Numbers are
only comparable across entries when the prompt set and methodology are
identical, which is enforced by version-controlling the prompts inside
`scripts/benchmark_gpu_inference.py`.

## How to add an entry

1. Run the benchmark from the repo root:
   ```
   C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe scripts\benchmark_gpu_inference.py
   ```
2. Copy the printed Markdown entry from stdout and paste it as a new `###`
   section below (newest at the top).
3. Fill in the `driver_version` field manually from Device Manager or
   `dxdiag`.
4. Commit alongside any code change that motivated the measurement.

### Companion standing measurements (added across the 2026.2.x campaign)

The generation benchmark above is the spine. Three companion harnesses are now
part of the standing methodology — run them alongside it when a change could
affect performance:

- **Dedicated prefill benchmark** — `scripts/benchmark_prefill.py`. Measures
  prompt-processing throughput (pp) at several fixed input lengths (512 / 2048 /
  8192 tokens), N=5 repeats, no-draft, prefix-caching OFF (cold prefill). Far
  tighter than the single-shot pp side-probe in `benchmark_gpu_inference.py`
  (single-digit pp std), so it is the trustworthy source for a prefill version
  A/B. The OpenVINO version is stamped into the output for cross-release A/Bs.
- **Per-run GPU telemetry (UT pass)** — `scripts/capture_single_ut.ps1` wraps a
  single-model run in Intel Unified Telemetry (foreground) and records per-phase
  iGPU power / frequency / GPU-busy % / bandwidth. This is a SEPARATE, annotated
  series from the UT-free comparable numbers (UT capture overhead lowers
  throughput slightly) — kept distinct so the baseline comparison stays clean.
- **Co-residency** — `docs/performance/README_coresident_ut.md` (the 14B + a
  second model on one iGPU, Intel-UT instrumented).

## Metrics glossary

| Metric | Meaning |
|--------|---------|
| **TTFT** | Time-to-first-token (ms) — from generation dispatch to the first streamed token, timed by a streaming callback. Reported **n/a** when the backend delivers no incremental tokens (the speculative / ContinuousBatching backend does not stream). |
| **Total latency** | Wall-clock time for the full generation (ms). |
| **Throughput** | Output tokens per second = `token_count / (total_latency_ms / 1000)`. |
| **mean / median / P95** | Statistics across all measured runs × all prompts for that config. |
| **spec-off / spec-on** | Two engine configs run back-to-back. "achieved" reflects what the engine actually used (spec-on can fall back to spec-off if draft model absent). |

---

### 2026-07-02 — First grammar-constrained tool call on the real 14B, and the first measured ISS-3 number (#717, #718)

**What changed:** #718 replaced the homemade `<tool_call>NAME(args)</tool_call>`
format with the Qwen3-native JSON form and enabled the xgrammar structural-tags
constraint (`[generation].tool_call_grammar = true`) on the production
speculative-decoding pipeline. This entry records the FIRST live run of that
stack on the real hardware, plus the first model-in-the-loop Policy Agent (PA)
classification measurement from the new `evals/` harness (#717) — the number
ISS-3 has been missing since it was opened.

**Hardware / stack:** Intel Core Ultra 7 258V (Lunar Lake), Arc 140V iGPU
(driver 32.0.101.8826), 32 GB LPDDR5X. OpenVINO GenAI 2026.2.1, Qwen3-14B
INT4-GPU + Qwen3-0.6B pruned-6L INT8 draft (spec-decode ON), xgrammar backend.
Machine-readable: `docs/performance/tool_call_native_round_trip_2026-07-02.json`
+ `phase2_gates/evidence/eval_pa_classification_model_897afd9.json`.

**Methodology:** (a) `tests/harness/test_tool_call_native_round_trip.py` —
the real AO `_handle_connection` turn (sprint-12 harness pattern), prompt
"What time is it right now?", grammar ON, greedy decoding, spy-wrapped
`parse_tool_call`/`execute`, N=1 (a mechanics verify, not a latency campaign);
(b) `evals/run.py --suite pa_classification --include-hardware` — 8 model-mode
golden probes through the real 14B classifier + 22 deterministic CAR cases.

**Results:**

| measurement | value |
|---|---|
| 14B model load (spec-decode, warm cache) | 10.76 s |
| tool round-trip turn total (call + dispatch + final answer) | 4 795.8 ms |
| generations in loop | 2 (tool call, then answer) |
| tool-call emission form | native JSON, zero legacy-fallback hits, zero fail-closed drops |
| PA classification (deterministic CAR, 22 cases) | 22/22 |
| PA classification (model-mode, 8 cases) | 4/8 — **all 4 misses are false DENIES of benign actions** |
| PA overall (30 evaluated) | 26/30 = 86.7 % |

**NOT measured:** tool round-trip latency distribution (N=1), grammar-compile
first-token overhead isolation, co-resident contention, multi-tool chains
(the loop currently dispatches one tool per iteration).

**Reading:** the native-format migration took on the first live turn — the
model emitted schema-valid JSON under the grammar with the draft engaged, and
the retired legacy form never fired. The ISS-3 finding is now quantified and
has a direction: the model-judgment layer OVER-DENIES (0 dangerous-action
false-allows, 4/8 benign false-denies). That is the safe failure direction,
but it is a real usability tax — dispositioning it (prompt tuning vs few-shot
vs accepting the bias) is an LA call, now decidable from data.

**Addendum (same day) — the #719 retrieval-tool live smoke:** with
`search_knowledge` registered (seeded runner over the real seam,
`tests/harness/test_search_knowledge_live_smoke.py`), the real 14B CHOSE the
retrieval tool for a knowledge question with no prompting beyond the tools
block — query `'hostname of my NAS'`, k=4 (clamp default), native JSON
emission, turn total 5 742.6 ms (2 generations), model load 11.3 s, the
result grounded with UNTRUSTED_KNOWLEDGE provenance (Layer-3 feedstock
flipped; Stage-5 leakage feed stayed exempt), and the final answer used the
seeded fact. One benign xgrammar warning (special-token id out of tokenizer
range) — the same cosmetic artifact the #718 offline probe recorded. N=1
mechanics verify; latency distribution NOT measured.

### 2026-07-02 — The idle NPU earns the embedding job; Whisper tries the same door and the device hangs (#720)

**What changed:** the shared bge-small-en-v1.5 embedding workload (substrate
memory + knowledge bank + PGOV Stage-5 leakage — all one `LeakageDetector`
session) gained a `[embeddings].device` knob (CPU = the ONNX Runtime path
that was production until today; GPU/NPU = OpenVINO compiling the SAME fp16
ONNX). Default flipped **CPU → NPU** on the strength of this measurement.
Whisper STT was probed on the NPU and measured NOT viable — it stays on GPU.

**Hardware / stack:** Intel Core Ultra 7 258V (Lunar Lake), Arc 140V iGPU
(driver 32.0.101.8826), Intel AI Boost NPU (driver 32.0.100.4778), 32 GB
LPDDR5X. OpenVINO 2026.2.1-21919, onnxruntime 1.24.2, Python 3.11.9.
Machine-readable: `docs/performance/embedding_device_2026-07-02_00-10-26.json`
+ `docs/performance/whisper_device_2026-07-02_00-13-38.json`.

**Methodology:** production surface (`LeakageDetector(device=...)`,
`_embed` @128 / `embed_documents` @512), 3 warmups then N=20 timed runs per
case, isolation (NO Qwen3-14B loaded). NPU is static-shape: two compiled
windows (128/512), inputs padded to the window, batch = one text per infer.
Harness: `scripts/benchmark_embedding_device.py` (reproducible, committed).

**Embedding latency (mean ms, warm):**

| case | CPU (ORT, prior default) | GPU (OV dynamic) | NPU (OV static) |
|------|-------------------------:|-----------------:|----------------:|
| single short @128 | 7.0 | 1.5 | 5.6 |
| single long (\~420 words) @512 | 168.9 | 7.5 | 12.4 |
| batch-8 @128 | 49.4 | 3.2 | 23.1 |
| batch-32 @128 | 186.0 | 6.9 | 85.6 |
| batch-8 short-texts @512 | 52.0 | 2.9 | 78.2 |
| load/compile (s) | 8.5 | 2.2 | 12.1 cold / \~2.5 blob-cached |
| load RSS delta (MB) | 522 | 408 | 228 |
| min cosine parity vs CPU | — | 1.000000 | 0.999996 |

**Reading:** the GPU is the fastest executor by far — and the wrong one: it
is the device the resident 14B contends for. The NPU beats the CPU path
13.6x on document-window texts (the knowledge-ingest / substrate case),
2.2x on batch-32, and holds parity on short singles, at near-identical
numerics (min cosine 0.999996 — the PGOV Stage-5 thresholds calibrated on
CPU numerics carry over). Its one loss — short texts padded to the 512
window (78 vs 52 ms) — is a padding artifact; real 512-window inputs are
long chunks, where the NPU wins 13.6x. The static-compile boot cost (12.1 s
cold) is amortized by a compiled-blob cache under
`%LOCALAPPDATA%/BlarAI/ov_cache/embeddings` (\~2.5 s warm, measured; the 14B
deliberately runs uncached because its 9 GB blob cold-reads as slowly as a
fresh compile — a 128 MB encoder is the opposite case).

**Whisper STT on NPU — negative result (recorded, not shipped):**
`openvino_genai.WhisperPipeline(models/whisper-small/openvino, "NPU")`
COMPILES (34.5 s) but the first `generate()` fails with
`ZE_RESULT_ERROR_DEVICE_LOST` (NPU device hang/reset; Level Zero
`zeCommandQueueExecuteCommandLists`, code 0x70000001) on this
driver/runtime combo. The GPU control run: 6.9 s load, **270 ms** mean
transcribe for an 8.7 s utterance (Kokoro-synthesized locally), verbatim
transcript. STT therefore STAYS on GPU; the NPU recovered cleanly after
the reset (bge-small NPU round-trip re-verified green). Harness:
`scripts/benchmark_whisper_device.py`.

**NOT measured:** co-resident Qwen3-14B contention (the operator was away;
the mission barred loading the 14B) — the isolation numbers above therefore
UNDERSTATE the NPU's production advantage (CPU/GPU slow under a generating
14B; the NPU does not). A resident-14B A/B is the natural follow-up.
Also not measured: the semantic-router ORT session (separate consumer,
CPU-targeted, not in the live turn path), the openvino-int8 IR precision
variant, corpus-level Whisper WER, sustained/thermal behaviour.

---

### 2026-07-01 — KV-cache precision at long context: INT8 is the sweet spot, and the fanless chip has two thermal tells

First long-context (16K/32K) **KV-cache precision** sweep for the 14B on the Arc
140V, and the entry that a broken first attempt (Vikunja #709) forced us to earn.
The original sweep copied the production `SchedulerConfig` (`cache_size = 3` GB),
which starves the KV cache at long context — Qwen3-14B needs \~160 KiB/token of KV
at FP16 (2 x 40 layers x 8 KV-heads x 128 head_dim x 2 bytes), so 32K needs 5.0
GiB and does not fit in 3, forcing block eviction + prefill recompute (TTFT 310s,
wild variance). The new harness (`scripts/benchmark_kv_cache_sweep.py`) sizes
`cache_size` per (precision, context) from the analytical KV need, rebuilds a
fresh pipeline per combo, and — because the chip is fanless — warms to a thermal
plateau then measures all combos back-to-back at that steady state.

**Hardware:** Intel Core Ultra 7 258V (Lunar Lake) + Arc 140V (Xe2 iGPU, shared
LPDDR5X, 31.323 GiB effective ceiling), GPU driver 32.0.101.8826.
**Runtime:** OpenVINO GenAI 2026.2.1.0 / OpenVINO 2026.2.1.
**Model:** Qwen3-14B INT4 (u4 weights), GPU, plain autoregressive (no draft),
prefix-caching OFF, `INFERENCE_PRECISION_HINT=f16`, `GPU_ENABLE_SDPA_OPTIMIZATION=ON`.
**KV precision** set via the GPU `KV_CACHE_PRECISION` property (`u8`/`u4`; FP16 =
property unset). **Methodology:** steady-state — warm to a TTFT plateau (reached in
6 iters: 131.5s → 46.1s), then N=3 per combo, back-to-back, no cooldown, median
reported. Prompt = version-controlled filler, unique nonce per rep (cold prefill).
TTFT = streamer first-token wall-clock minus dispatch.

| KV precision | KV @ 32K | TTFT 16K (median) | TTFT 32K (median) | TPOT 32K |
|---|---|---|---|---|
| **FP16** (unset) | 5.00 GiB | **45,796 ms** (std 27) | **368,853 ms** (std 5,044) | 160 ms |
| **INT8** (u8)    | 2.50 GiB | 46,814 ms (median; see note) | **158,995 ms** (std 552) | 160 ms |
| **INT4** (u4)    | 1.25 GiB | 51,457 ms (std 590) | 174,486 ms (std 2,009) | 163 ms |

**Two regimes.** At **16K** prefill is compute-bound: KV quantization is slightly
*slower* (dequant overhead, no bandwidth relief yet) — FP16 fastest, INT4 +12%.
At **32K** prefill is memory-bandwidth-bound reading the large KV cache every
step, so quantization is a big *speed* win: **INT8 is 2.3x faster than FP16**.
**INT8 is the sweet spot** — INT4 saves the most memory but its 4-bit dequant
cost makes it slightly slower than INT8 (174s vs 159s). The non-monotonicity
(INT4 slower than INT8 at 32K) is itself evidence the effect is a compute/bandwidth
tradeoff, not simply thermal (thermal would scale monotonically with prefill
duration).

**The memory lever** is the KV footprint itself: INT8 halves it, INT4 quarters it
(5.0 / 2.5 / 1.25 GiB at 32K) — measured analytically from geometry; the reserved
KV pool shows as `cl_mem` in `GPU_MEMORY_STATISTICS` (tracking `cache_size` to the
byte), model weights as `usm_host` (\~7.9 GiB). On this shared-LPDDR5X iGPU
`usm_device` stays \~0; host system-RAM is only a coarse whole-footprint proxy.

**Two fanless-chip thermal tells, documented honestly:**
1. **Cold-start ramp** — from idle the iGPU downclocks hard; the first 1-2 heavy
   prefills run slow (\~131s at 16K) while the clock ramps and first-run kernels
   compile, then it snaps to the warm plateau (\~46s). This is why the harness
   warms to plateau before measuring. (An earlier hypothesis that a slow first
   combo was *residual heat* was wrong — the warm-up ramp gets *faster*, not
   slower, which only fits a cold-clock/first-run effect.)
2. **Long-prefill self-throttle** — the very long 32K prefills self-heat the chip;
   within the FP16-32K combo TTFT drifts up mildly (364.2 → 376.4s) as it runs.
   Stable enough for a median, but real.

**Not measured (named, not implied):** GPU frequency / temperature / rail-power
traces — so the 32K INT8-vs-FP16 mechanism (bandwidth vs any residual thermal
amplification) is *strongly indicated* but not instrumented here. A follow-up UT
(Intel Unified Telemetry, `scripts/capture_single_ut.ps1`) pass is ticketed to
confirm it with freq/temp/power. Also not measured: speculative decoding at long
context (this is the plain target pipeline), and KV precision above 32K.

**Data note:** the u8-16K first rep was a 75.6s post-pipeline-rebuild transient;
the N=3 median (46.8s) excludes it and matches FP16 (validating median + N=3).
Machine-readable: `docs/performance/kv_cache_sweep_ov2026_2_1_0_2026-07-01_19-10-33.json`
(per-rep TTFT, warm-up ramp, and per-combo memory retained). The two superseded
runs (starved-budget and thermally-confounded) are kept under
`docs/performance/_invalid/` with validity blocks, not published.

---

### 2026-06-30 — UC-010 dispatch asset generation (SEAM A): the cartoon generator, live on the Arc 140V

First community-grade numbers for the **dispatch asset generator** — the base-SDXL `illustration`/`cartoon` path (#703) that BlarAI's headless-coding dispatch now calls to produce real raster app assets (UC-010 SEAM A, #714). Measured **standalone** (no resident 14B) via a direct `image_gen.generate_text2image` on the real signed-manifest-verified model.

- **Hardware:** Intel Core Ultra 7 258V (Lunar Lake) / Arc 140V (Xe2) iGPU; 31.323 GB shared ceiling.
- **Runtime:** OpenVINO 2026.2.1 (`openvino_genai` Text2ImagePipeline).
- **Model:** base Stable Diffusion XL 1.0, OpenVINO INT8 (nncf weight-only) + the DD-vector flat-vector LoRA applied at runtime (alpha 0.8, NOT fused).
- **Config:** 1024×1024, 30 steps, EULER_ANCESTRAL_DISCRETE, guidance 7.0, hires OFF, `require_signed_manifest=true`.
- **Methodology:** 2 sequential generates (seed 42, then 7); first = load+generate, second = generate-only (pipeline resident); RAM sampled at 5 Hz for the peak.

| metric | value |
|---|---|
| model load (est.) | \~34.8 s |
| generate / image (1024²/30 steps) | \~59.9 s |
| load + first generate | \~94.7 s |
| RAM used before | 8.8 GiB |
| RAM peak (standalone, no 14B) | 18.7 GiB |
| output PNG | 1024×1024, \~812 KB |

**Not measured here (named honestly):** 14B co-residence — this standalone generate runs WITHOUT the resident 14B. The 14B+SDXL **co-resident** peak (\~26.0 GB, 5.3 GB headroom) is the ADR-033 §Memory Phase-0 record (`docs/performance/image_gen_phase0_2026-06-16.json`); SEAM A runs in that envelope (base 1024² keeps the 14B). VLM/voice co-residence not measured. The image-model + 30B-coder co-residence is FORBIDDEN by design (32.5 GB breach) — which is why SEAM A generates pre-swap. Machine-readable: `docs/performance/uc010_dispatch_asset_gen_2026-06-30.json`.

**Read:** 30 steps at \~2 s/step is the honest cost of the quality-tuned EULER_ANCESTRAL config; a draft-quality dispatch asset can drop steps (the config knob) to trade fidelity for speed. The generated cartoon elephant — a real raster, coherent subject on a clean solid background — is the SEAM-A "after" that replaces the hand-drawn inline `<svg>`.

### 2026-06-29 — Co-residency on 2026.2.1: the pattern holds — a resident 14B still loses its iGPU to a generating roommate

A confirmatory refresh of the #705 co-residency study on OpenVINO 2026.2.1 (N=1 per
pairing — the full N=3 variance study is the published 2026.1.0 dataset; this checks
the pattern survives the version bump). The resident Qwen3-14B (spec-on) shares the
Arc 140V with a second model; measured at baseline-alone, partner-resident-idle, and
sustained contention, with foreground Intel UT. All four pairings **fit** under the
31.323 GiB ceiling, and the contention behaviour reproduces 2026.1.0:

| Partner | 14B gen: baseline → idle → contention | peak co-resident | headroom |
|---|---|---|---|
| SDXL photoreal | 18.5 → 18.4 → **0.1 tok/s (1%)** | 27.05 GiB | 4.27 |
| SDXL illustration | 19.0 → 18.4 → **0.1 (1%)** | 26.91 GiB | 4.42 |
| SDXL cartoon (LoRA) | 17.7 → 19.0 → **2.5 (14%)** | 28.82 GiB | 2.50 |
| Qwen3-VL-8B | \~18 → \~18 → **2.0 (10%)** | 25.00 GiB | 6.32 |

The story is unchanged: **idle co-residence is \~free** (the resident 14B keeps full
throughput while a partner sits loaded), but **concurrent generation saturates the
iGPU and starves the 14B.** The mechanism, from the UT telemetry (photoreal): under
contention GPU-busy → **99.99%** while memory-read bandwidth *drops* (66 → 18.9
GB/s) — the exhausted resource is **compute scheduling, not bandwidth or clock**
(core stays \~1948 MHz). Compute-bound SDXL diffusion stalls the 14B to \~1%; the
bandwidth-bound VLM leaves it \~10%; the cartoon LoRA's CPU-side overhead leaves
scheduling gaps so the 14B retains \~14% (read as "mildest pressure," partly a
fixed-window spin-up artifact — a steady-state re-run is the cleaner number, open
follow-up). GT-rail power \~9.3 W and SoC temp \~78 °C under contention; NPU 0 W.

**Bandwidth unit caveat (unchanged, stated plainly):** UT reports
`GPU_MEMORY_BYTE_*_RATE` with unit N/A; idle \~66, peak \~103–107 vs the \~136 GB/s
LPDDR5X ceiling strongly implies GB/s but it is UNCONFIRMED. Per-run UT metrics:
`docs/performance/coresident/ut_hardened/ut_{photoreal,illustration,cartoon,vlm}_r1.*`;
harness JSONs `benchmark_coresident_*_2026-06-29_*.json`.

---

### 2026-06-29 — OpenVINO 2026.2.1, the rest of the campaign: prefill and the VLM are the real wins; the MoE flag has a price

The 14B and 8B entries below show generation throughput is unchanged 2026.1.0 →
2026.2.1. This entry covers the rest of the 2026.2.1 benchmark campaign — and the
upside the generation numbers hide. Same stack (Arc 140V, driver 32.0.101.8826).
Where a version A/B is shown, the 2026.1.0 side was measured in a SEPARATE venv
(`openvino 2026.1.0 / genai 2026.1.0.0`), back-to-back with 2026.2.1, same harness
— the runtime venv was never downgraded.

**Prefill (prompt processing) is meaningfully faster on 2026.2.1 — the headline
upside.** A dedicated, multi-length, multi-repeat prefill harness
(`scripts/benchmark_prefill.py`, cold prefill, no draft, prefix-cache off) measured
both versions back-to-back (pp = tokens/sec the model READS input at):

| INT4 model | length | 2026.1.0 | 2026.2.1 | change |
|---|---|---|---|---|
| 14B | 512 | 595 | 761 | **+28%** (tight, std<10) |
| 14B | 2048 | 426 | 747 | +75% (noisier, std \~60) |
| 14B | 8192 | 277 | 388 | +40% |
| 8B | 512 | 1086 | 1477 | **+36%** (tight) |
| 8B | 2048 | 716 | 1106 | +54% (noisier) |
| 8B | 8192 | 592 | 627 | +6% |

Every length on both models is faster on 2026.2.1. The tightest-measured points
(512 tokens) show a solid +28–36%; mid-range gains are larger but higher-variance.
Faster prefill = faster first token on long prompts. (The single-shot pp probe in
`benchmark_gpu_inference.py` had hinted at this — "8B pp doubled" — but it was one
noisy sample; the dedicated harness confirms a real, if smaller, win. This is why
the prefill harness is now a standing companion measurement.)

**The VLM is faster too (PR #3640).** Qwen3-VL-8B-Instruct INT4 on a fixed
image+prompt: TTFT 201 → 162 ms (**\~19% faster** on 2026.2.1), TPOT 63 → 47 ms,
load \~7.8 → 7.4 s. The 2026.1.0 run was noisier on TPOT, so TTFT is the solid
claim. `vlm_perf_ov*_*.json`.

**The 30B MoE accuracy flag has a real throughput price.** OVMS 2026.2 is unchanged
(the OFF arm reproduces the 2026-06-28 baseline: 38.6 vs 38.1 median — no version
delta). The `MOE_USE_MICRO_GEMM_PREFILL=0` flag (added 2026-06-29, on in production
to recover MoE INT4 accuracy on long prompts) costs more than its "slight TTFT
cost only" label:

| Qwen3-Coder-30B-A3B | gen median | TTFT median | coding eval (2.2K ctx) |
|---|---|---|---|
| flag ON (=0, accuracy) | 31.3 tok/s | 236 ms | 4/5 |
| flag OFF (default) | 38.6 tok/s | 184 ms | 4/5 |

The flag costs **\~19% generation throughput AND \~28% TTFT**, and on a defined,
ground-truth coding eval at 2.2K-token context the two arms scored **identically
(4/5, same answers)** — no measurable accuracy benefit at that scale (its documented
benefit is on much longer repo-scale prompts this eval did not reach). Net: a
measured tradeoff worth revisiting — the flag is currently paying a real throughput
cost for accuracy that this eval could not demonstrate. (The eval needs an 8K–32K
context to probe the regime where the flag is meant to help — a follow-up.)
`benchmark_ovms_coder-30b_2026-06-29_*.json`, `coding_eval_30b_moe_{on,off}_*.json`.

**KV-cache precision (u8 / u4) — the memory lever could NOT be quantified this way
(honest null).** The GPU plugin accepts `u4` (confirmed) and `u8`. But sweeping
{FP16, u8, u4} × {16K, 32K} on the 14B, peak shared-RAM (In-Use = Total − Available)
was **flat at \~20.85 GB across every precision AND both context lengths**. If the
KV cache were visible to host-RAM sampling, 32K would be \~2× the KV of 16K and u4
well below FP16 — it wasn't. That is the signature of a load-time GPU memory pool
that system "Available" sampling cannot resolve on this unified-memory iGPU. So the
headline hypothesis (INT4-KV freeing RAM for the hires-SDXL path) is **unconfirmed**
and needs GPU-allocation-level instrumentation, not host Available. TTFT at 32K was
also pathological/unstable in this harness. Reported as a named limitation, not a
fabricated saving. `kv_cache_sweep_*.json`.

**min_p (non-default sampling what-if).** Production is greedy (temp=0), so
`min_p` is a what-if for `do_sample=True`. At temp 0.8, sweeping min_p {0, 0.05,
0.1}, the distinct-trigram ratio (higher = less repetition) rose 0.983 → 0.992 —
min_p modestly reduces degenerate repetition, no latency cost. Small effect because
the 14B at temp 0.8 already repeats little. A reasonable default IF sampling is ever
enabled. `minp_ab_*.json`.

**SDXL (1024², 20 steps, 2026.2.1):** photoreal 30.0 s / 15.4 GB peak, illustration
31.3 s / 15.2 GB, cartoon (DD-vector LoRA) 37.4 s / 16.8 GB (the LoRA adds \~6 s gen,
\~1.5 GB, \~17 s load). `sdxl_latency_2026-06-29_*.json`.

**What is NOT measured / open:** the KV memory lever (method limitation, above); the
MoE flag's accuracy benefit at 8K–32K context (eval too short); EAGLE-3 (conversion
blocked upstream). N is modest (prefill N=5; VLM/SDXL/min_p N=2–3); single machine.

*(2026.2.1 campaign; gen-neutral but prefill + VLM materially faster, MoE flag a
measured cost. Co-residency refresh + commits pending.)*

---

### 2026-06-29 — OpenVINO 2026.1.0 → 2026.2.1: the 14B version delta is a no-op, and CPU-draft is a clean negative

This is the first entry of the **2026.2.1 benchmark campaign** (Session 2 of the
upgrade-and-remeasure effort), run under the EXACT committed 2026.1.0 baseline
methodology so the numbers are directly comparable: prompt-set v1, 5 measured + 2
warmup, `--run-cooldown 30`, greedy (`do_sample=False`), GPU draft = same device
as target. **Stack:** Intel Core Ultra 7 258V (Lunar Lake) + Arc 140V (Xe2,
shared LPDDR5X-8533, 31.323 GiB), **GPU driver 32.0.101.8826 held constant**,
Windows 11 Pro, **OpenVINO GenAI 2026.2.1.0 / openvino 2026.2.1 /
openvino-tokenizers 2026.2.1.0** (in-process). LOCALAPPDATA redirected.

**Headline: the 2026.1.0 → 2026.2.1 in-process bump is performance-neutral on the
Qwen3-14B INT4.** Median generation throughput, holding everything else constant:

| 14B INT4 | 2026.1.0 (baseline) | 2026.2.1 | delta |
|---|---|---|---|
| spec-off (autoregressive) | 11.13 tok/s | 10.92 | flat (within run-to-run noise) |
| spec-on (GPU draft, 0.6B-pruned-6L) | 17.07 tok/s | 17.20 | flat |
| spec-on prefill (pp) | \~1308 | \~1881* | (pp is a single-token timing, high variance) |
| spec-on TTFT (median) | 470 ms | 468 ms | flat |

Per-prompt medians are near-identical (e.g. spec-on p1/p2/p3 = 15.7/18.7/21.3
vs baseline 15.7/18.7/21.4). The comparable 2026.2.1 14B run is
`docs/performance/benchmark_2026-06-29_10-57-25.json`.

**A contamination lesson worth keeping.** My first 2026.2.1 spec-on run read
14.64 tok/s median (−14%) while spec-off stayed flat. That looked like a version
regression — but the cause was a couple of **browser windows open on the box**
during that run. Speculative decoding is **compute-scheduling-bound**: the draft
and target both contend for the iGPU's Xe scheduling, so a background GPU consumer
(a browser compositor) knocks \~14% off spec-on while leaving the steady
autoregressive path untouched. Re-running on a quiet, dedicated machine restored
spec-on to 17.20. The contaminated run is excluded from the comparable, but it is
a clean little demonstration of *how* scheduling-sensitive spec-decode is — a free
corroboration of the co-residency study's "the exhausted resource is compute
scheduling, not bandwidth" finding. The lesson: a single background GPU client can
masquerade as a runtime regression; verify the environment before believing the
delta.

**Draft device: GPU draft vs CPU draft (new this campaign).** Production runs the
0.6B draft on the GPU (same device as the target). The untested option is a CPU
draft — on a discrete GPU that can be a win (frees the GPU, overlaps draft/verify),
but on a *unified-memory* iGPU the CPU draft pulls the same LPDDR5X and adds a
CPU↔GPU sync per speculation round, so it is genuinely empirical. Measured (greedy,
num_assistant_tokens=3):

| 14B spec-on | GPU draft | CPU draft |
|---|---|---|
| gen median (spine methodology) | 17.20 tok/s | 14.88 tok/s (\~13% slower) |
| draft acceptance (accepted/proposed) | 45.0 % | 45.1 % (identical) |
| accepted / generated | 59.8 % | 59.8 % |
| GT (graphics) rail power, decode | 6.8 W | 5.3 W |
| package power, decode | 23.8 W | 24.5 W |
| SoC temp, decode | 67.6 °C | 69.4 °C |

**Acceptance is identical** because the draft device doesn't change *which* tokens
a greedy draft+target pair propose and accept — only how fast the draft produces
them; this is a useful consistency check (and it validates the acceptance probe).
The CPU draft is \~13% slower with no acceptance benefit, and the telemetry shows
why it's a *lose-lose*: it shifts \~1.5 W of draft compute off the graphics rail
onto the CPU/package (package power up, SoC temp up) for *less* throughput. The
bottleneck was never GPU-compute availability, so offloading the draft just adds
CPU power and heat. **CPU-draft is a net loss on Arc 140V / Lunar Lake — keep the
draft on the GPU.** (NPU-draft is a separate question, deferred — the NPU is
ADR-011-retired and a prior NPU-draft attempt hit issues.) Data:
`docs/performance/benchmark_2026-06-29_11-37-59.json` (CPU-draft spine),
`draft_device_accept_{gpu,cpu}_*.json` (acceptance probe).

**New methodology track — per-run GPU telemetry on single-model runs.** Alongside
the comparable UT-free spine (above), each single model now also gets a separate,
clearly-annotated **foreground Intel-UT pass** (socwatch + level-zero) so we
accumulate per-run iGPU power / frequency / GPU-busy % / bandwidth over time. The
UT pass is *not* the comparable number (its capture overhead + shorter run lower
throughput slightly — e.g. 16.8 vs 17.2 for the 14B); it is a labelled new
series. **14B spec-on decode steady-state (GPU draft):** GT rail 6.8 W avg / 9.2 W
1 s-peak, package 23.8 W / 30.5, GPU-busy \~89 %, core clock \~1925 MHz (peak 1949),
GPU memory read \~67 GB/s (peak \~107 — unit reported N/A by UT, almost certainly
GB/s vs the \~136 GB/s ceiling, **unconfirmed**), SoC temp 67.6 °C. NPU 0 W
(pure-GPU, ADR-011). Per-phase JSON: `ut_14b_specon_clean.{socwatch,l0}.metrics.json`.

**What is NOT measured here:** answer-quality deltas (none expected — greedy
decoding is deterministic and acceptance is identical); the KV-cache-precision and
min_p knobs (separate entries); co-resident cost (separate study); a same-process
2026.1.0 A/B — the 2026.1.0 side is the committed baseline run under identical
methodology, not a back-to-back A/B. N=5 (spine) / N=2 (UT pass), single machine.

\* The spec-on prefill pp jumped from \~1308 (baseline) to \~1881 (2026.2.1) — but
prefill pp is measured from a single `max_new_tokens=1` generation and is
high-variance; spec-off pp is steady (\~1960 → \~1870). Treat pp as indicative, not
a precise version delta.

---

### 2026-06-29 — OpenVINO 2026.1.0 → 2026.2.1: the 8B is also a no-op, same CPU-draft verdict

Companion to the 14B entry above, same campaign, same methodology (prompt-set v1,
5 measured + 2 warmup, `--run-cooldown 30`, greedy, GPU draft = target device),
same stack (Arc 140V, driver 32.0.101.8826, OpenVINO GenAI 2026.2.1.0). Measured
on a quiet, dedicated machine. **Qwen3-8B INT4** target, same Qwen3-0.6B-pruned-6L
INT8 draft as the 14B.

**Version delta — performance-neutral**, same as the 14B:

| 8B INT4 | 2026.1.0 (baseline) | 2026.2.1 | delta |
|---|---|---|---|
| spec-off (autoregressive) | 19.79 tok/s | 19.62 | flat |
| spec-on (GPU draft) | 27.37 tok/s | 27.09 | flat |
| spec-on TTFT (median) | 313 ms | 316 ms | flat |

Per-prompt medians near-identical. Comparable run: `benchmark_2026-06-29_11-51-39.json`.

**Draft device (GPU vs CPU) — same clean negative as the 14B:**

| 8B spec-on | GPU draft | CPU draft |
|---|---|---|
| gen median (spine) | 27.09 tok/s | 23.48 tok/s (\~13% slower) |
| draft acceptance (accepted/proposed) | 48.3 % | 48.1 % (identical) |

Acceptance is identical across device (as expected) and **higher than the 14B's
45%** — the 0.6B draft is a closer approximation to the 8B than to the 14B, so
more of its speculated tokens are accepted. CPU-draft is again \~13% slower for no
acceptance benefit → net loss; keep the draft on the GPU. Data:
`benchmark_2026-06-29_12-22-22.json` (CPU-draft spine),
`draft_device_accept_8b_{gpu,cpu}_*.json`.

**UT Pass B (telemetry track) — 8B spec-on decode steady-state (GPU draft):**
GT rail 5.8 W avg / 8.7 peak, package 21.9 W / 28.8, GPU-busy \~85 %, core clock
\~1929 MHz, GPU memory read \~66 GB/s (peak \~107, unit unconfirmed), SoC 63.8 °C,
NPU 0 W. Slightly below the 14B across the board (smaller, faster model = less
sustained compute). `ut_8b_specon.{socwatch,l0}.metrics.json`.

**What is NOT measured:** answer-quality deltas (greedy + identical acceptance →
none expected); prefill A/B (the standing `scripts/benchmark_prefill.py` runs it
in the 2026.1.0 restore window). N=5 (spine) / N=2 (UT, draft-device probe),
single machine. The 2026.1.0 side is the committed baseline, not a same-process A/B.

*(campaign in progress; commits pending.)*

---

### 2026-06-28 — What the resident 14B costs a roommate: co-residency on one iGPU, Intel-UT instrumented

**This is a measurement entry** — the follow-on the operator asked for after the (a) refresh below:
*what does it cost the always-resident Qwen3-14B (spec-on) to share the Arc 140V with each model it
might run beside?* Four pairings, **N=3 repeats each**, every run wrapped in **Intel Unified Telemetry**
(`ut.exe`, socwatch + level-zero) for real GPU power / frequency / busy / memory-bandwidth —
publishing-grade for the OpenVINO community, not just wall-clock. Hardware: Intel Core Ultra 7 258V
(Lunar Lake) + Arc 140V (Xe2 iGPU, shared LPDDR5X-8533, 31.323 GiB effective), driver 32.0.101.8826,
OpenVINO GenAI 2026.1.0. Dataset: `docs/performance/coresident_14b_pairings_hardened_2026-06-28.json`;
reproduce via `docs/performance/README_coresident_ut.md`.

Three states per pairing: **baseline** (14B alone), **idle** (second model resident but not generating),
**contention** (second model generating continuously while the 14B runs back-to-back for a fixed 15 s
window — a sustained probe that kills the overlap-timing noise of the first pass).

**Memory — every pairing fits, with room:**

| pairing (second model) | partner resident | peak co-resident | headroom |
|---|---|---|---|
| photoreal — SDXL-uncensored INT8 `/imagine` | 5.45 GiB | 25.91 GiB | 5.41 GiB |
| illustration — base SDXL 1.0 INT8 `/illustrate` | 5.59 | 26.13 | 5.19 |
| cartoon — SDXL + DD-vector LoRA `/cartoon` | 5.77 | **27.59** | **3.73** |
| vlm — Qwen3-VL-8B INT4 (vision) | 5.31 | 24.55 | 6.77 |

(14B alone resident \~9.2 GiB; the second model adds \~5.3–5.8 GiB; peak co-resident during a real 1024²
generate / vision op stays 24.5–27.6 GiB against the 31.323 ceiling. cartoon is tightest. HIRES image
gen is **not** in this table — it evicts the 14B by design, ADR-033 Am.2.)

**Throughput — idle co-residence is \~free; concurrent generation is brutal, but how brutal depends on the partner:**

| pairing | 14B baseline gen | 14B idle gen (tax) | 14B contention gen | contention TTFT |
|---|---|---|---|---|
| photoreal | 19.82 tok/s | 19.89 (\~0%) | **0.22 (1.1%)** | 13.6 s |
| illustration | 19.81 | 19.60 (\~1%) | **0.19 (1.0%)** | 14.9 s |
| cartoon | 19.46 | 19.39 (\~0%) | **3.27 (16.8%)** | 0.87 s |
| vlm | 19.13 | 18.10 (**5.4%**) | **2.58 (13.5%)** | 1.08 s |

(means of N=3; full ± std in the dataset. Baseline gen drifts 18.9–19.9 run-to-run, so the SDXL idle
"tax" is within noise — effectively free; the VLM's \~5% idle tax is the one consistent resident cost. The
14B cold-prefill baseline is \~1140 pp tok/s; the idle-state pp figure in the dataset is cache-warm and
**not** a clean prefill measure.)

**The mechanism — what's exhausted under contention is GPU *compute scheduling*, not bandwidth and not the
clock.** Across all pairings the GPU goes to \~99% busy and stays pinned at \~1.95 GHz with **zero throttle**
(`IGFX-THROT-RSN` = 0 every run) — the starvation is occupancy, not frequency or thermal. The *bandwidth*
signature, though, splits by partner type:

| pairing | GPU busy idle→cont | mem-read idle→cont (GB/s*) | iGPU rail idle→cont (W) |
|---|---|---|---|
| photoreal | 90.8 → 99.9% | 72.5 → 23.6 | 8.59 → 11.61 |
| illustration | 90.3 → 99.8% | 69.2 → 21.3 | 8.53 → 11.00 |
| cartoon | 82.2 → 98.8% | 57.3 → 47.0 | 8.38 → 8.61 |
| vlm | 88.2 → 98.7% | 66.7 → 61.3 | 8.10 → 8.30 |

- **SDXL diffusion (photoreal, illustration) is compute-bound** and monopolizes the EU scheduler so
  completely that the 14B can't even finish its *prefill* inside the 15 s window — TTFT blows out to 13–15 s
  and only 4 tokens emerge → a near-total stall (\~1%). Aggregate memory-read *drops* (≈70→22 GB/s) because
  the bandwidth-bound 14B decode can't get the compute slots to *issue* its reads. These two also draw the
  most iGPU-rail power under load (11+ W) — the heaviest pure-GPU pressure.
- **The VLM is itself a bandwidth-bound transformer**, so contention keeps memory-read high (67→61 GB/s) and
  the 14B holds 13.5% — it recovers between the VLM's short 8 s describe bursts.
- **cartoon (SDXL + runtime LoRA) is the mildest SDXL pressure** (16.8%) and the highest-variance. Several
  independent signals agree it monopolizes the GPU *less* than plain SDXL — fast TTFT (0.87 s), lower busy
  (98.8%), higher retained bandwidth (47 GB/s), lower rail power (8.6 W): the DD-vector LoRA's CPU-side
  application leaves GPU scheduling gaps the 14B slips through. (Caveat below.)

**Power / thermal / NPU:** package power \~24–26.5 W throughout; iGPU rail peaks (1 s-windowed) 10–13.5 W. SoC
peaks \~80–82 °C, CPU \~90–95 °C under contention, **no GPU throttle** any run. **`PMT-NPU-PWR` = 0.0 W in
every phase of every pairing** — a clean, twelve-times-repeated confirmation that BlarAI is pure-GPU
(ADR-011); the NPU is never touched.

**Caveats (read before citing):**
- **Sustained-contention is a fixed-15 s-window probe.** cartoon's milder figure partly reflects partner
  spin-up/overlap landing inside that window (hence its higher variance); a follow-up that warms the partner
  to steady-state first would isolate steady-state diffusion contention.
- **`GPU_MEMORY_BYTE_*_RATE` unit is reported N/A by UT** — almost certainly GB/s (idle \~67–72, peak \~108 vs
  the \~136 GB/s LPDDR5X ceiling) but UNCONFIRMED; marked `*` above.
- **level-zero per-phase via a validated linear clock-remap.** UT flags a "timestamp-units" driver issue, so
  l0 sample timestamps aren't Unix-epoch (measured \~27.7 h offset from socwatch in-session); per-phase l0 is
  recovered by anchoring the l0 range linearly onto socwatch's Unix window from the same capture session
  (`extract_ut_metrics.py --remap-from`). Validated 2026-06-28 — remapped contention samples show the
  expected busy spike and the freq/busy/bandwidth split is physically coherent. socwatch power/thermal is
  natively Unix-epoch (no remap needed).
- **Power** = socwatch energy (mJ/sample) → W; avg = total mJ / total ms; peak = max over 1 s windows (raw
  per-sample peak is meaningless — sub-ms samples produce spurious \~kW glitches).

**Next:** the dataset is ready for OpenVINO-community contribution. Open follow-ups: (1) a steady-state
cartoon/LoRA contention run to remove the spin-up confound; (2) confirm the `GPU_MEMORY_BYTE_*_RATE` GB/s
unit against a known-bandwidth microbench; (3) optional system-wide DDR bandwidth via emon EDP (deferred —
emon's stop-phase hangs UT finalization). The headline for the operator's question stands: any one of these
models can sit resident beside the 14B for \~free; running two generators at once on the single iGPU is the
real cost, and the 14B is the one that yields.

*(Co-residency study; 12 runs, Intel-UT instrumented; commit `<this>`. Supersedes the noisy first-pass
`coresident_14b_pairings_ut_2026-06-28.json` (left uncommitted). Captured foreground after the background
sweep was reaped twice — see the BUILD_JOURNAL fragment. Vikunja #705.)*

---

### 2026-06-28 — The (a) benchmark refresh: 14B + 8B + 30B on the current stack, with the new pp metric

**This is a measurement entry** — the deferred (a) follow-up to the 2026-06-27 cross-runtime
analysis below. Three models re-benchmarked on the current hardware/stack with **5 measured + 2
warmup runs each** and `--run-cooldown 30` (thermal fairness), now capturing **pp (prompt-processing
throughput, tok/s)** alongside generation throughput + TTFT. pp closes the prefill-comparability gap
the 2026-06-27 entry flagged. Driver **32.0.101.8826**, Arc 140V (16 GB), 26 GB free at run time.

**Runtime split (load-bearing for the record):** the in-process assistant models (14B, 8B) run on
**OpenVINO GenAI 2026.1.0** (the BlarAI venv); the coder 30B runs on **OVMS 2026.2** (a separately
installed, newer OpenVINO — OV backend 2026.2.0-21902, GenAI 2026.2.0.0). So the three are not on one
runtime version; each section states its own. (This corrects the 2026-06-27 caveat that assumed the
box had moved wholesale to 2026.2.)

Result JSONs: `docs/performance/benchmark_2026-06-28_00-27-22.json` (14B),
`benchmark_2026-06-28_00-44-13.json` (8B), `benchmark_ovms_coder-30b_2026-06-28_08-32-38.json` (30B).

#### Qwen3-14B INT4 — OpenVINO GenAI 2026.1.0, GPU (+ Qwen3-0.6B-pruned-6L INT8 draft)

| Metric | spec-off (median) | spec-on (median) |
|--------|-------------------|------------------|
| Throughput (tok/s) | 11.1 (mean 10.1, P95 11.9) | **17.1** (mean 16.1, P95 21.5) |
| Prefill pp (tok/s) | **1960** (mean 1877, P95 2005) | 1308 (backend artifact — see notes) |
| TTFT (ms) | 466 | 471 |

Spec-on is a **\~1.54x generation speedup** (the 252-token prompt sustained 21.5 tok/s), and it is
**up from the stale 2026-05-22 figure of 13.6 tok/s** — the tuned pruned-6L draft on the current
stack. `speculative_decoding_active=True` confirmed. Load \~8.6 s (warm).

#### Qwen3-8B INT4 — OpenVINO GenAI 2026.1.0, GPU (+ the same 0.6B draft)

| Metric | spec-off (median) | spec-on (median) |
|--------|-------------------|------------------|
| Throughput (tok/s) | 19.8 (mean 16.2, P95 21.1) | **27.4** (mean 21.9, P95 29.7) |
| Prefill pp (tok/s) | **1968** (mean 1978, P95 2028) | 1748 (backend artifact) |
| TTFT (ms) | 264 | 313 |

The 0.6B draft accelerates the 8B too (shared Qwen3 vocab) — **\~1.38x**. First spec-on number on
record for the 8B. Cold first-load \~22 s (uncached compile); warm reload \~9 s.

#### Qwen3-Coder-30B-A3B INT4 — OVMS 2026.2, GPU (continuous batching)

| Metric | median | mean | P95 |
|--------|--------|------|-----|
| Throughput (tok/s) | **38.1** | 34.9 | 38.8 |
| Prefill pp (tok/s) | 480 | 458 | 495 |
| TTFT (ms) | **214** | 226 | 323 |

OVMS flags: `target_device GPU, kv_cache_precision u8, enable_prefix_caching true, tool_parser
qwen3coder, enable_tool_guided_generation true, cache_size 4`. Confirms the prior \~37-39 single-stream
baseline. Bench: `scripts/benchmark_ovms_http.py` over the loopback OpenAI-compatible endpoint.

#### Observations

- **The MoE profile, now measured both ways.** The 30B-A3B has the **fastest decode** (38 tok/s,
  \~2x the dense 14B spec-on) and the **fastest TTFT** (214 ms), but the **slowest prefill** (pp \~480,
  \~1/4 the dense 14B/8B \~1960). MoE decode touches only \~3B active params; MoE *prefill* routes every
  prompt token across all 128 experts, paying \~30B compute. Dense models are the mirror image —
  heavier decode, lighter prefill. This is the single most useful shape in the dataset.
- **Read each pp in its own context — it is not a clean cross-model A/B.** The in-process pp is over
  \~970 *formatted* tokens (BlarAI's chat template + system prompt); the OVMS pp over \~421
  *bare-message* tokens (no system prompt); and the runtimes differ (2026.1 vs 2026.2). Each pp is
  internally valid for that model. The MoE-vs-dense prefill gap (\~4x) is far larger than those
  confounds could account for, so the directional finding stands.
- **spec-on pp is a backend artifact, not a regression.** The pp probe (`max_new_tokens=1`) on the
  speculative ContinuousBatching backend reads low (1308/1748) because that single token still pays
  draft+target overhead. The **spec-off pp (\~1960) is the true prefill rate** — prefill is
  config-independent, so the two should match; the spec-off number is the one to cite.
- **Greedy-path divergence between backends.** At temperature 0, spec-on occasionally produced a
  different token count than spec-off for the same prompt (e.g. 14B P1: 48 vs 62 tokens). The standard
  pipeline and the ContinuousBatching/spec engine take slightly different greedy paths; it does not
  affect the tok/s measurement, but it means spec-on is not bit-identical output here.
- **vs community (the 2026-06-27 entry).** pp closes the prefill gap the analysis flagged: BlarAI's
  dense prefill **\~1960 tok/s is \~3.7x the community llama.cpp/SYCL 7B pp512 (\~536)** on the same Arc
  140V silicon. Generation: 14B spec-on 17.1 firmly fills the community's missing 14B-on-GPU datapoint.

**Methodology:** `scripts/benchmark_gpu_inference.py` (14B/8B) + `scripts/benchmark_ovms_http.py`
(30B), prompt-set v1 (byte-identical across both harnesses), pp probe pp-v1 (unique per-run prefix so
prefix-caching cannot serve a cold prefill). 5 measured + 2 warmup, 30 s run-cooldown, greedy
(temperature 0). Co-resident cost NOT measured — each model was benchmarked alone (the 30B and the 14B
cannot co-reside in 31.3 GB).

---

### 2026-06-27 — Cross-runtime comparison: BlarAI's OpenVINO numbers vs community llama.cpp/SYCL on the Arc 140V (ANALYSIS — no new hardware run)

**This is an analysis entry, not a measurement.** It triangulates the existing dated entries in
this log (BlarAI's own OpenVINO GenAI numbers on the Arc 140V) against community-measured
**llama.cpp / SYCL** figures for the *same* Arc 140V silicon, pulled 2026-06-27 via a deep-research
sweep (primary sources — llama.cpp docs/issues, Intel/OpenVINO docs, arXiv, GitHub API — with 3-vote
adversarial verification). No model was run for this entry. It exists because (a) the User-Operator
asked how BlarAI's measured prefill/generation compares to the community, and (b) it partially fills a
gap the research itself flagged: there is **no published OpenVINO-vs-llama.cpp head-to-head on the
140V**. BlarAI's log is the OpenVINO half. Machine-readable sidecar (numbers + sources + verification):
`docs/performance/openvino_vs_community_llamacpp_arc140v_2026-06-27.json`.

**Methodology mismatch — the load-bearing caveat.** BlarAI's `benchmark_gpu_inference.py` measures
**generation throughput** (output tok/s) + **TTFT** (time-to-first-token, a *latency*). Community
`llama-bench` reports **pp512** (prompt-processing *throughput*, tok/s) + **tg128** (generation
throughput, tok/s). So **generation compares directly; prefill does not** — BlarAI currently records
prefill only as a TTFT latency, not a pp throughput. Closing that is the (a) follow-up — **and the pp tok/s
metric has now been added to `benchmark_gpu_inference.py` and unit-tested ahead
of the run** (see **Next**).

**BlarAI measured (this log, OpenVINO GenAI, Arc 140V):**

| Model (role) | Precision | Generation (tok/s) | TTFT | Source entry |
|---|---|---|---|---|
| Qwen3-14B (assistant), standard | INT4 | \~10.6 median (P95 11.5) | \~0.77 s | 2026-05-22 |
| Qwen3-14B, spec-decode ON | INT4 | \~13.6 median (P95 16.8; 16.5 on a 252-tok prompt); by context 12.2@2K / 9.6@8K / 4.9@16K | n/a (no stream) | 2026-05-22, 06-05 |
| Qwen3-Coder-30B-A3B (coder, MoE \~3B active) | INT4 / OVMS | \~37–39 single; \~93 aggregate @ 8-way | — | 2026-06-21, 06-27 |
| Qwen3-VL-8B (vision) | INT4 | \~8–16 decode | — | 2026-06-03/04 |

**Community llama.cpp / SYCL (Arc 140V, pulled 2026-06-27):**

| Model (size, quant) | Runtime | pp512 (prefill) | tg128 (gen) | Source / quality |
|---|---|---|---|---|
| 7B dense Q4_0 | llama.cpp SYCL | \~536 | \~24.6 | forum llama-bench, Jun 2026 |
| 7B dense Q4_0 | IPEX-LLM (archived) | 708 | 24.4 | llm-tracker, Nov 2024 |
| 7B dense Q4_0 | llama.cpp Vulkan | 45 | 5.5 | llm-tracker, Nov 2024 (weak on iGPU) |
| 8B dense Q4_K_M | IPEX-LLM/Ollama | — | 17–18 | gist, n=1, Jun 2026 |
| 8B dense INT4 | OpenVINO | — | \~12 | Julien Simon, Apr 2025 |
| 14B dense Q4 | llama.cpp | — | \~4.3 | LocalScore, **likely CPU** |

**Findings.** (1) **BlarAI's 14B is competitive AND fills a real gap** — a 7B at \~24.6 tg scaling to a
14B (2× params) at \~13 tg is the \~half-speed a memory-bandwidth-bound doubling predicts, and the
community has *no* trustworthy 14B-on-GPU number (the only one, \~4.3, is almost certainly CPU). BlarAI's
\~13 tok/s spec-on is the datapoint the web couldn't produce. (2) **The 30B-A3B is the standout** —
\~38 tok/s beats every community dense-7B, because mixture-of-experts active-params (\~3B) drive speed.
(3) **OpenVINO quietly beats the runtime hobbyists default to** — IPEX-LLM (their fastest turnkey path)
is archived/security-flagged (2026-01-28); Vulkan is \~5.5 tok/s on this iGPU. (4) **BlarAI's numbers are
the more rigorous side** — 5 runs + 2 warmup + thermal cooldown, vs the community's mostly single-run
blog/forum figures.

**Caveats / not-compared.** Cross-runtime + cross-model triangulation, not an A/B (OpenVINO vs llama.cpp;
different model families and quants). Community figures are mostly n=1. **BlarAI's 14B numbers are stale
relative to its own stack** — measured May-2026 on OpenVINO 2026.1 + the January driver
(32.0.101.8424); the box has since moved to OpenVINO 2026.2 + the May driver (32.0.101.8826) for the 30B
work, and the 14B/8B have not been re-benchmarked there (community SYCL generation *doubled* over the
same window, so BlarAI's may have moved too). Prefill is not yet apples-to-apples.

**Next:** the (a) refresh — re-run **Qwen3-14B + Qwen3-8B (`models/qwen3-8b/openvino-int4-gpu`) +
Qwen3-Coder-30B-A3B**, **≥5 measured runs each** (+2 warmup, `--run-cooldown 30` for thermal fairness),
on the current OpenVINO 2026.2 + driver 32.0.101.8826, **with the new pp (prompt-processing) tok/s
metric** so prefill compares directly to community pp512. The pp metric (a fixed \~450-token probe →
`max_new_tokens=1` prefill timing → `pp = input_tokens / prefill_s`, probe `pp-v1`) plus a model-name
de-hardcode (`--model-name` / `_derive_model_name`) are **now implemented + unit-tested**
(`test_benchmark_helpers.py`, 49 passed) ahead of the run; only the on-hardware execution remains. 14B/8B
via `benchmark_gpu_inference.py` (`--model-dir models/qwen3-8b/openvino-int4-gpu` for the 8B); the 30B via
the OVMS-HTTP path (requires OVMS serving the 30B). **Deferred until the active headless-coding dispatch
build frees the GPU/OVMS.** Then fold the fresh numbers into this comparison and its JSON sidecar.

*(Analysis only; community sources + verification in the JSON sidecar. No code or model changed by this entry.)*

---

### 2026-06-27 — OVMS continuous-batching concurrency on the Arc 140V (best-of-N parallelism, #695)

The question #695 had to answer on the box, not predict: can headless-coding best-of-N candidates
run CONCURRENTLY through OVMS continuous batching on the *integrated* Arc 140V (shared LPDDR5X, no
discrete VRAM), and what is the real ceiling? Measured against the resident coder — **Qwen3-Coder-30B-A3B**
(qwen3_moe, 30B total / \~3B active), INT4 weights (16.3 GB IR), OVMS **2026.2**, `--task text_generation`
(continuous batching), `--target_device GPU`, `--cache_size 4` GB, `--kv_cache_precision u8`,
`--enable_prefix_caching true`. GPU driver 32.0.101.8826 (2026-05-28). Method: N identical
`POST /v3/chat/completions` requests fired simultaneously (thread pool), temperature=0, max_tokens=200,
one warm-up first; the OVMS server log's `llm_executor` ticks give `All requests / Scheduled requests /
cache usage %`.

Short-prompt sweep (175-char prompt):

| N | wall (s) | aggregate tok/s | speedup vs N=1 | mean lat (s) | max lat (s) | per-req tok/s |
|---|----------|-----------------|----------------|--------------|-------------|---------------|
| 1 | 5.11 | 39.1 | 1.00x | 5.11 | 5.11 | 39.2 |
| 2 | 10.10 | 39.6 | 1.01x | 10.08 | 10.10 | 19.8 |
| 4 | 10.90 | 73.4 | **1.87x** | 10.88 | 10.90 | 18.4 |
| 8 | 17.24 | 92.8 | **2.37x** | 12.79 | 17.23 | 15.8 |

Long-context burst (the realistic best-of-N case — each request a **6,675-token** context): 8 concurrent
→ wall 36.75 s, aggregate 40.8 tok/s, and the OVMS log showed **7-8 sequences scheduled concurrently at
just 10.5% of the 4 GB cache.**

Three findings. **(1) Continuous batching engages** — OVMS scheduled up to 7-8 concurrent sequences and
aggregate throughput rose 1.87x (N=4) and 2.37x (N=8). **(2) The KV cache is NOT the constraint for
best-of-N** — eight 6.7K-token contexts cost only 10.5% of the pool, because `enable_prefix_caching`
stores the SHARED best-of-N prompt once and `u8` halves the KV bytes; the cache could hold far more.
**(3) The binding constraint is COMPUTE** — the integrated GPU saturates (\~40-90 tok/s aggregate), so the
concurrency speedup is real but SUB-LINEAR and per-request latency grows with N (5.1 s → 17.2 s at N=8).
Net: running candidates concurrently cuts wall-clock to the best result \~1.9x (N=4) to \~2.4x (N=8),
cache-cheap, with C beyond \~4 buying little.

**NOT measured (named):** full multi-minute `opencode` agent-run concurrency (only raw single-request
batching — an agent run is many sequential requests, so candidate-concurrency ≈ one in-flight request per
candidate, which this approximates); per-candidate solve-rate under concurrency (a quality question);
N > 8 and cache/precision tuning beyond the shipped config. Machine-readable:
`docs/performance/dispatch_concurrency_arc140v_2026-06-27.json`.

**Recommendation [PROPOSED → LA]:** parallelism is viable and cache-cheap; wire concurrency as a config
knob defaulting to **C=1** (today's sequential), with **C=2-3** the proposed production default once a live
concurrent dispatch is signed off. Defaulting C>1 is a resource/behaviour posture call reserved for the LA.

---

### 2026-06-27 — UC-010 three image styles end-to-end on the Arc 140V: /imagine + /illustrate + /cartoon, production path (#703)

The #703 live-verify generated one image per shipped style through the **real** `shared.inference.image_gen`
engine with **production** safety settings — `require_signed_manifest=true` (the detached
`manifest.json.sig` must verify at load) plus the cartoon LoRA SHA-256 integrity pin
(`b4c8132f…fe89`) checked before the runtime adapter is applied. `is_available=true` for all three.
Machine-readable sidecar: `docs/performance/uc010_image_styles_arc140v_2026-06-27.json`.

| Style (command) | Model | Adapter | Cold E2E (load+compile+gen) | Output PNG |
|---|---|---|---|---|
| photoreal (`/imagine`) | RealVisXL V5.0 (SDXL-arch) INT8 | none | **43.8 s** | 1.46 MB |
| illustration (`/illustrate`) | SDXL 1.0 base INT8 | none (flat prompt only) | **39.8 s** | 680 KB |
| cartoon (`/cartoon`) | SDXL 1.0 base INT8 | DD-vector LoRA @ runtime (α 0.8, **never fused**) | **60.6 s** | 237 KB |

**Methodology — the load-bearing caveat.** These are **cold** numbers. The harness configures a style,
generates ONE 1024×1024 image (30 steps, EULER_ANCESTRAL_DISCRETE, guidance 7.0), then `unload()`s before
the next style — so each latency is *lazy pipeline load + INT8 GPU compile + generate*, single run (n=1),
**not** the steady-state generate-only figure (prior UC-010 entries measured generate-only \~10.7 s at
1024px). Runtime: OpenVINO **2026.1.0** + GenAI 2026.1.0 on the Arc 140V; driver 32.0.101.8826 (last
recorded 2026-06-24, not re-verified this run). Memory not sampled this run.

**Findings.** Cartoon is slowest (60.6 s) because applying the LoRA at runtime adds a compile/blend cost on
top of the base load — that cost is *deliberate*: fusing the vector LoRA into the INT8 base collapses prompt
conditioning (the #703 root cause), so the runtime-adapter path is the correct trade. Illustration is
fastest (39.8 s) — base SDXL + a flat-style prompt, no finetune-load or adapter overhead. Output byte size
tracks style and corroborates three genuinely distinct renders: cartoon 237 KB (flat, minimalist) <
illustration 680 KB (bold flat-vector) < photoreal 1.46 MB (photographic entropy).

**Next:** isolate steady-state generate-only latency per style (warm pipeline, no eviction) and sample the
resident footprint of the runtime-LoRA path, to publish a generate-only + memory companion to these cold
end-to-end numbers.

*(Live-verify n=1 per style, production settings. Code on `feat/703-illustrate-cartoon`; gate 4606 passed/0 failed.)*

### 2026-06-25 — Playground v2.5 (OV-INT8) CPU text2image latency + rembg cutout (dispatch asset-gen, UC-010 Phase 2b)

**What:** the build-time dispatch asset pipeline (gen → rembg background-removal → clean isolated subject
on transparent) measured on **CPU**. The GPU was occupied by the dispatch's resident 30B coder (OVMS), and
co-residing Playground + 30B was the measured 32.5 GB ceiling breach, so the standalone proof runs on CPU.
Machine-readable: `docs/performance/playground-v2.5-int8-cpu-assetgen-2026-06-25.json`. Proof-grade
(single-run), NOT a rigorous multi-run benchmark.

**Setup:** OpenVINO **2026.2.1**, device **CPU** (Intel Core Ultra 7 258V, Lunar Lake), optimum-intel 2.0.0,
diffusers 0.37.1, torch 2.12.1, `rembg[cpu]` (u2net), isolated Python 3.11.9 venv
(`blarai-build/img-convert/venv311`), `OVStableDiffusionXLPipeline`, guidance 3.0, model-default scheduler.

**Measurements (CPU, single-run):** model load **\~9 s**; text2image **512²/20 steps = 141 s**,
**768²/28 steps ≈ 473–485 s** (3 samples); rembg cutout **< 1 s/image** (u2net).

**Not measured:** GPU latency (Phase-3 swap-sequence path), co-resident memory cost, multi-run variance,
1024² CPU latency (skipped for time).

**Finding:** the gen → rembg → cutout pipeline is proven — rembg removes the cluttered background in under a
second **when the generation yields a distinct subject**. Generation prompt/setting tuning is the quality
lever (over-emphasising "empty white space" pales the subject; under-constraining lets the SDXL mosaic
clutter fill the whole frame, leaving nothing to isolate), and it iterates far faster on the GPU — the
Phase-3 path. CPU is usable for a proof but slow (\~8 min at 768²/28).

---

### 2026-06-24 — Playground v2.5 illustration model (OV-INT8) on Arc 140V: resident footprint \~8.4 GB + 1024px speed

**What:** the SECOND UC-010 image model — Playground v2.5 (`playgroundai/playground-v2.5-1024px-aesthetic`),
an SDXL-architecture aesthetic model chosen for illustration assets — converted to OpenVINO INT8 and
measured for (a) resident RAM footprint and (b) generation speed on the Arc 140V. Captured for the
swap-budget math behind the planned image-gen + VLM-design-loop dispatch phases. Machine-readable:
`docs/performance/playground-v2.5-int8-arc140v-2026-06-24.json`.

**Setup:** OpenVINO **2026.2.1-21919**, Arc 140V driver **32.0.101.8826**, optimum-intel 2.2.0 export
(`--weight-format int8`), isolated Python 3.11 venv, `OVStableDiffusionXLPipeline`. INT8 model is \~3.3 GB
on disk. RAM sampled with `psutil.virtual_memory().used` (system in-use) as deltas; generation device=GPU.

**Resident footprint (delta-isolated from a co-resident 30B coder):** loading Playground added **+8.16 GB**;
the peak during a 1024×1024 generation reached **+8.42 GB**. So the illustration model's real residency is
\~8.2 GB loaded / \~8.4 GB at peak — well above a naïve \~5–7 GB guess; measuring beat estimating.

**Speed (GPU, Arc 140V):** 1024×1024 at 30 steps (guidance 3.0, model-default scheduler) rendered in
**\~36 s** (\~1.2 s/step). A CPU smoke at 512×512 / 20 steps took **157 s** (\~7.85 s/step) — sub-minute on
the iGPU, \~13× slower on CPU.

**Co-residence finding (load-bearing for the design):** baseline with the 30B coder loaded was 24.12 GB;
adding Playground pushed the system to a **32.54 GB peak — over the 31.32 GB ceiling by \~1.2 GB**, i.e. it
only "fit" by paging to disk. **The image model and the 30B coder cannot truly co-reside;** the UC-010
dispatch design must swap one model resident per phase (Playground alone, \~8.4 GB, fits comfortably).

**Not measured / caveats:** the footprint was captured WITH the 30B co-resident, so the 8.42 GB peak ran
under \~1.2 GB paging pressure (the 8.16 GB load delta is clean); a clean ALONE re-measure (30B stopped)
would give a publication-clean peak. Image quality not benchmarked here (subjectively: good flat subjects,
cluttered/painterly backgrounds — flat-vector needs background-removal or a LoRA). INT8-vs-FP16 and GPU
power/thermal not captured this run.

---

### 2026-06-24 — Dispatch 30B-coder build: power profile + the no-OOM mechanism corroborated live (run 20260624-120231-bd)

**What:** the FIRST full `/dispatch` build on the swapped-in 30B coder — power draw across
NPU/package/iGPU/CPU during a sustained agentic build, plus a live corroboration of the
no-OOM memory mechanism the milestone-1 swap gate first measured. Complements the
`2026-06-21` entry (which measured the swap *headroom gate* + a 30B *load* certification);
this is the *sustained build* power, a workload milestone-1 did not cover. Machine-readable:
`docs/performance/dispatch_swap_telemetry_2026-06-24.json`.

**Hardware/SW:** Core Ultra 7 258V / Arc 140V (Xe2), 31.32 GB LPDDR5X, Shared-GPU override
\~87% (window \~27 GB); OpenVINO 2026.1 (driver version NOT captured this run — recorded as a
gap). **Model:** Qwen3-Coder-30B-A3B INT4 (the coder, OVMS native-Windows GPU via qwen-proxy
:8099); the resident Qwen3-14B was SWAPPED OUT for the build.

**Method:** a REAL `/dispatch` build (`rocket-calc`, a full themed WinUI goal), not a
synthetic benchmark — it ran \~60 min and PARKED after 2 build passes (the park is a
build-framework result, recorded in the dispatch journal + #676, not a perf result).
Telemetry: Intel Unified Telemetry 0.2.0-beta1.1 (socwatch + emon, `--config-level low`)
over the build-TAIL + swap-back window (13:05–13:30, \~25 min, \~650k samples); a 5 s
`FreePhysicalMemory` sampler (Tier-0) over the build. The swap/30B-LOAD window was NOT
cleanly captured this run (see the lesson) — the load-trough figures below are cited from
the milestone-1 measurement, not re-measured here.

**Numbers (build-tail window, averaged; per-sample peaks are counter-rollover artifacts and are excluded):**
- **NPU: \~0 W** — idle the entire build (a known offload opportunity, not a new finding).
- **Package: \~20.9 W avg**; **iGPU: \~5.8 W avg**; **CPU cores: \~9.6 W avg**.
- Tier-0 build-phase min free RAM **\~2.2 GB** (steady, post-load — NOT the load trough).

**The no-OOM mechanism (the headline) — why a \~29 GB load survives a 31 GB box:** OOM fires
on **commit charge > commit LIMIT**, not on working-set > physical RAM — and those are
different numbers here. Commit limit = physical RAM + pagefile = **31.32 + \~11 = 42.32 GB**
(measured this session; pagefile peak-ever-used 3.36 GB). The 30B load is a **\~29 GB
committed transient** — under 42.32 GB, so **no OOM**. What DID happen (measured at
milestone-1, corroborated here): physical headroom exhausts — Available RAM craters to **\~67
MB** while Committed peaks **\~29.1 GB**, and the overflow modified-pages spill to the
pagefile (the \~180–206k pages/s storm milestone-1 caught; the 3.36 GB pagefile peak is that
spill). Three things make the too-big-for-physical-RAM load survive: (1) **swap-first** —
releasing the 14B frees \~11 GB before the 30B loads, lowering the baseline; (2) the **commit
limit > the transient** — the \~11 GB pagefile lifts the ceiling 31→42 GB, so \~3.3 GB lives
on disk briefly instead of OOM-killing; (3) the **87% Shared-GPU-Memory-Override** gives the
iGPU a \~27 GB window into the unified pool. After the storm the working set settles and the
build runs with a few GB free.

**Not measured (named, per community-grade discipline):** this run's EXACT load-trough
(sampler died + restarted after the 12:15 load; the UT running through the load was stopped
unflushed — the trough figures above are milestone-1's, not re-measured); DDR bandwidth
(captured in the 417 MB EMON `.bin`, not extracted); the swap/load POWER window (UT lost);
GPU driver version (not captured); build-time decode tok/s.

**Capture-method lesson (carried to the dispatch journal):** Intel UT buffers in RAM and
writes ONLY at `-t` completion — it does NOT flush on kill. A too-long `-t` (I set 2400 s)
buffered 2.34 GB and had to be killed to protect the run, losing the window. Next run: a
SHORT pre-sized `-t` that self-completes over the known load window, armed BEFORE approval,
never killed mid-capture; plus a sub-second memory sampler for the trough.

### 2026-06-21 — 14B in-process release/reload memory behavior (headless-coding swap, milestone-1) — openvino #33896 does NOT bite on the Arc 140V

**What:** the memory-domain gate for the headless-coding model swap — can BlarAI's
resident 14B be released to free the unified pool for a 30B coder (OpenVINO Model
Server), and does the integrated-GPU shared-memory carve-out physically return on an
*in-process* release (openvino #33896: Lunar Lake iGPU memory is not auto-freed on
idle)? Machine-readable: `docs/performance/milestone1_14b_release_2026-06-21.json`.

**Hardware/SW:** Core Ultra 7 258V / Arc 140V (Xe2), 31.323 GB LPDDR5X, Shared-GPU
override \~87% (window \~27 GB); driver 32.0.101.8826; OpenVINO + GenAI 2026.1.0.
**Model:** Qwen3-14B INT4 + Qwen3-0.6B-pruned-6L INT8 draft (spec-decode), prefix
caching on, device=GPU — built via `build_shared_pipeline` (same as production boot).

**Method:** 3-cycle `measure → unload() (drop refs + 1× gc.collect) → 60 s
stability-gated settle → measure → reload (fresh build) → coherence`, two configs:
B1 (standalone throwaway) and B2 (the SAME unload driven inside the live long-lived
launcher process — authoritative for #33896, via a flag-gated sentinel hook removed
at run end). Per-PID GPU via `\GPU Process Memory(*)\Local Usage`; RAM via
`\Memory\Available MBytes` cross-checked with Committed Bytes + Free&Zero (rules out
standby inflation). A process kill was deliberately NOT used — it always frees the
GPU and would prove nothing about the in-process path the swap performs.

**Numbers (B2, live, per cycle, stable):**
- per-PID GPU Local Usage: **10,774 → 677 MB** (\~10.1 GB returned), settles in **\~1 s**, stays down (zero residue across cycles).
- `unload()` returns in **\~1.0 s**; reload (fresh build) **\~18.5 s**, coherent (not garbled).
- Available RAM **\~11.6 → \~22.0 GB**; Committed Bytes drops \~11.3 GB and Free&Zero rises \~11 GB in lockstep → the free is **genuine**, not standby cache.
- The 2nd `gc.collect()` (diagnostic) frees nothing — one collect suffices.

**Finding:** **#33896 does NOT manifest on this stack** — the in-process release
returns the full carve-out without a restart; the swap's release mechanism is sound.
RAM clearance CLEARS the 30B's \~21 GB peak gate (lands \~22 GB) but by a **thin \~1 GB
margin** that is ambient- and KV-state-dependent (idle 14B frees \~8.7 GB; a heavier
ambient lands \~18 GB, short).

**Step 2 — 30B load CERTIFIED (same day):** with BlarAI down (lean ambient, 23.2 GB
free) the Qwen3-Coder-30B INT4 (OVMS, `--target_device GPU`) loaded in \~30 s and ran
at **37.4 tok/s** (≥ 35 → the \~87% Shared-GPU override is effective; brief §9 step 2
satisfied). Footprint **15.3 GB per-PID iGPU**, \~13.6 GB net pool, leaving \~9.6 GB
steady headroom; stops clean (RAM fully returns to 25.5 GB). The fleet's
`start-llm.ps1 -Force` was correctly **denied by the safety classifier** for skipping
the 21 GB gate; loaded via the gate-respecting non-`-Force` path with an explicit pre-check.

**The honest result is three cases, not a viable/not-viable binary:**

**(1) 14B release — SOUND.** #33896 doesn't bite; \~10 GB back in \~1 s, genuine, reversible,
coherent reload. Directly measured (B2, live process).

**(2) 30B standalone load on a leaned box — WORKS BUT MARGINAL.** The operator's daily
case: loads + runs at 37.4 tok/s from \~25 GB, but *barely* — Available hit 67 MB (19 MB
AV-off), Committed peaked 29.1 GB, a \~6 s page-storm (\~180–206k pages/s; AV-off unchanged,
so it's the dual CPU+GPU weight staging, not antivirus). **Correction:** the earlier
"Committed 29.1 < 31.3 ceiling so RAM never exhausted" was wrong — 31.3 GB is *physical*
RAM; the commit *limit* is higher (pagefile). There was no OOM (commit limit not hit), but
**physical headroom DID exhaust** (Available → \~0), and that exhaustion *is* the page-storm.
Marginal, not benign.

**(3) The actual swap — MEASURED.** Live BlarAI → release the 14B in-process → measure the
resulting headroom, from a real un-leaned \~19.9 GB cold ambient: the **bare swap** (BlarAI
stays alive) lands at **20.1 GB** Available (releasing the 14B freed +11.3 GB; backend GPU
8.7 → 0.65 GB; unload 1.4 s). **20.1 < 23.1 GB** (lowest measured successful 30B load) →
**sub-threshold**: the 30B load was correctly **not attempted** (it would death-spiral) and
the gate **aborts**. The swap-**back** leg is proven — the 14B reloads fresh in the live
process in \~21 s, coherent (GPU back to 11 GB). So the **bare swap is NOT viable**: BlarAI
staying resident keeps it \~2 GB below even the cold baseline, and from this ambient a full
BlarAI teardown (\~19.9 GB cold) is *still* sub-threshold unless non-BlarAI apps are trimmed.

**Conditional verdict:** release proven; standalone load proven-but-marginal; the **bare
swap is not viable** (measured 20.1 GB, sub-threshold). The swap is viable **only if** it
*actively* reaches ≥\~23–25 GB before the 30B load — full BlarAI step-aside **and** ambient
trim — and **verifies** it. The pre-load headroom check is the **load-bearing gate**: from a
real ambient it **aborts** (as it correctly did here), which is the point. **Surfaced:** the
21 GB gate is too low (peak 29.1 GB) *and* a leaner-ambient bare swap (\~22 GB) would *pass*
the 21 GB gate yet still sit below the 23.1 GB it needs; `-Force` skips the gate; the 14B is
host-side on the Arc. **Milestone-2** dispatch stays gated on the swap reaching a viable
headroom — the active-trim path's 30B load was deferred (it would reproduce the marginal
standalone case). (Earlier drafts swung viable→not-viable→viable on the same data; the full
arc is preserved in the journal fragment.)

### 2026-06-16 — UC-010 Local Generative Imaging Phase-0 memory spike (ADR-033, #666) — build-or-no-build GATE, PASSED on the Arc 140V

**What:** the build-or-no-build memory gate for UC-010 (local image generation). The
question the spike answers: does a diffusion model (uncensored SDXL INT8) co-resident
with the always-resident 14B + KV-cache fit under the 31.323 GB ceiling during a
1024² generate, WITHOUT evicting the 14B? It does, with headroom — so the build
proceeded.

**Hardware / stack (community-grade, reproducible):**
- CPU: Intel Core Ultra 7 258V (Lunar Lake)
- GPU: Intel Arc 140V (Xe2 iGPU), shared 31.323 GB system RAM ceiling (no dedicated VRAM)
- openvino-genai 2026.1.0.0-2957-1dabb8c2255; OpenVINO 2026.1.0
- GPU driver version: read from Device Manager / dxdiag at the on-chip session — NOT introspectable here
- Models co-resident: Qwen3-14B INT4 (target) + Qwen3-0.6B pruned-6L INT8 (draft) + RealVisXL V5.0 SDXL INT8 (nncf weight-only, diffusers-OV layout)

**Methodology:** with the 14B resident and a \~3k-token KV-cache populated, the §E
eviction path was exercised (`unload_vlm()` + the substrate `unload_embed_cache()`),
then the SDXL pipeline was loaded on-demand and a single 1024² image generated at
6 few-step (Lightning) steps; `log_memory` deltas were taken across load → generate →
unload. One generate, one config — a feasibility spike, not a throughput sweep.

**Measured:**
| Metric | Value |
|--------|-------|
| Co-resident peak (14B + \~3k KV + SDXL INT8 + 1024² generate) | **\~26.0 GB** |
| Headroom vs the 31.323 GB ceiling | **\~5.3 GB** |
| SDXL load (cold, on-demand) | **18.7 s** |
| 1024² generate (6 Lightning steps) | **10.7 s** |
| Swap-thrash / OOM | none observed |

**Verdict:** the budget closes WITH the 14B held resident → the "14B never evicted"
invariant holds → UC-010 build A–H proceeded. Fail-Soft means an unexpected OOM
degrades to an "unavailable" notice, not a host freeze.

**NOT measured (named honestly):** VLM + voice co-residency DURING a generate (the
eviction sequence removes them first, so this is the intended-absent cost, not an
unmeasured peak); dataset-calibrated INT8 quality; subjective image fidelity;
throughput across a prompt set / multiple resolutions (a single feasibility generate);
GPU driver version (read at the on-chip session). The community-grade LIVE numbers
(per-resolution latency, fidelity notes, the full eviction trace) land at the
LA-present go-live ceremony (ADR-033 §dormancy/go-live), NON-OPTIONAL.

Machine-readable: `docs/performance/image_gen_phase0_2026-06-16.json`.

---

### 2026-06-14 — Voice on-demand load/unload RAM reclaim (#660) — PROCEDURE SET UP, hardware run PENDING (LA live-verify)

**Status: NOT YET MEASURED — this entry documents the exact procedure and the
acceptance gate; the heavy real-model run is the Lead-Architect on-hardware
live-verify.** The build agent does not run the real Whisper/Kokoro load (per the
#660 boundary). The numbers table below is left blank deliberately — fill it from
a real run; do not infer it.

**What #660 added:** the WinUI voice toggles ("Voice replies / BlarAI speaks" =
Kokoro TTS; "Microphone / BlarAI listens" = Whisper STT) load each model on
demand when turned on and **unload it to reclaim RAM** when turned off. The unload
drops the model attribute on `VoiceEngine` and runs `gc.collect()` (mirrors the
#611 embedding-cache idle-unload). The headless tests prove the Python object is
genuinely dropped; **whether the C++/driver layer promptly returns RAM/GPU on
finalization is what this measurement settles** — and it is the genuine gate: if
the RAM does not come back, the toggle's promise is unmet (escalate, do not ship a
no-op that lies about reclaiming).

**Harness:** `scripts/benchmark_voice_ram.py` — drives the production engine
surface (`VoiceEngine.with_paths` → `load_stt`/`unload_stt`/`load_tts`/
`unload_tts`) and samples process RSS + system RAM (psutil) at each phase.

**Exact procedure (LA, on the Arc 140V box, models present under `models/`):**

1. Isolated baseline (voice in isolation, NO 14B resident):
   ```
   .venv\Scripts\python.exe scripts\benchmark_voice_ram.py
   ```
   This loads then unloads each half and prints/records the load delta + the
   reclaim delta (and the % of the load returned). JSON lands in
   `docs/performance/voice_ram_<timestamp>.json`.

2. Co-residency baseline (the production-relevant number — voice toggled WHILE
   the 14B is resident): bring up the real backend / the GPU-inference benchmark
   so Qwen3-14B is loaded, then read total system **In-Use** RAM
   (Total − Available, per the dev-machine RAM-accounting note — NOT working-set
   sums) immediately before and after toggling each voice half ON, then again
   after toggling OFF. Record both deltas.

3. (Optional, for a true GPU breakdown) capture Task Manager "GPU memory" or
   `xpu-smi` alongside step 2 — psutil reports system RAM, and on the Arc 140V
   (shared system RAM) that is a proxy, not a driver-level GPU readout.

**Config stamp (fill at run time):**

| Field | Value |
|-------|-------|
| Hardware | Intel Core Ultra 7 258V / Arc 140V (Xe2), 32 GB LPDDR5X |
| OpenVINO version | (fill: `python -c "import openvino; print(openvino.__version__)"`) |
| GPU driver version | (fill from Device Manager / dxdiag) |
| Models | Whisper-small (OpenVINO, GPU) + Kokoro-82M (ONNX) |
| Settle window | 2 s (default `--settle-s`) |

**Results — isolated run, 2026-06-14 (3× reproducible; the co-residency-with-14B column is still PENDING the LA's step-2 measurement):**

| Half | Load Δ (RSS) | Reclaim Δ (RSS) | % of load returned | Co-resident-with-14B load Δ | Verdict |
|------|--------------|-----------------|--------------------|-----------------------------|---------|
| STT (Whisper) | +752–875 MB | \~−80 MB | **\~10%** | pending (step 2) | **WEAK / NO RECLAIM** → killable-subprocess pivot (#660 follow-up) |
| TTS (Kokoro) | +378 MB | −426 MB | **113%** | pending (step 2) | **RECLAIM CONFIRMED** — ships in-process |

**Acceptance gate:** a half "reclaims" if a clear majority (the harness flags
≥50%) of its load delta returns on unload. If reclaim is weak/zero on the real
hardware, the in-process unload is insufficient and the design pivots to a
killable voice subprocess (escalate to the LA — that is a capability/architecture
decision, not a defect fix).

**What is NOT measured here (named explicitly):** GPU device-memory breakdown
(system-RAM proxy only on the shared-memory iGPU); peak footprint during an
actual transcribe/synthesize call (these are loaded-idle figures); and — unless
step 2 is run — the co-residency cost against the resident 14B + on-demand VLM.

**Finding (isolated run, 3× reproducible including with BlarAI closed / GPU free):**
Kokoro/ONNX (TTS) releases cleanly on in-process `del` + `gc.collect()` (113% of
the load returned); OpenVINO Whisper (STT) does NOT (\~10% returned, \~680 MB
pinned). → TTS ships in-process; the STT half pivots to a killable subprocess
(#660 follow-up). **Caveat:** all three runs logged reproducible oneDNN
`no opencl gpu device available` errors *even with BlarAI closed* → Whisper may be
running a CPU fallback rather than the Arc GPU — a separate performance concern
worth a look (relevant to the OpenVINO upstream work), tracked apart from #660.
JSONs: `docs/performance/voice_ram_2026-06-14_*.json` (3 runs).

### 2026-06-13 — Right-sizing the parser VM: Dynamic Memory reclaims \~1.5 GB; parser peak demand is 256 MB (#661)

Not an inference benchmark — a Hyper-V **VM memory** measurement. The
`BlarAI-Orchestrator` guest homes *only* the NIC-less trafilatura parser
(UC-003); the LLM/VLM/voice all run host-side, so every GB the VM pins is taken
from the 31.323 GB host budget. The VM was switched from **static 2 GiB** to
**Dynamic Memory (Min 512 MB / Startup 1 GB / Max 2 GB)** and the parser's
footprint measured to confirm the sizing is safe.

- **Hardware/stack:** Core Ultra 7 258V (Lunar Lake) host, Windows 11 Pro
  26200, Hyper-V Gen 2 VM (Alpine, NIC-less, kernel 6.12.x). The guest parser is
  **CPU** lxml/trafilatura — no GPU — so OpenVINO / GPU-driver versions are
  **N/A** for this measurement. Host driver: Python 3.14.4, in-process
  AF_HYPERV over the existing vsock parse channel (the production
  `make_health_probe` / `parse_round_trip` harness — no live `/ingest <url>`;
  the egress door stays welded).
- **Methodology** (reproducible: `scripts/measure_guest_parser_memory.py`,
  deterministic \~248 KB synthetic article near the 256 KiB channel cap): cold
  boot → await parser READY → sample `Get-VM` MemoryDemand/MemoryAssigned across
  rest, a **60 s sustained burst** of near-cap parses, and settle (\~1.5 s
  cadence). The burst — not a single parse — is deliberate: a 248 KB parse
  finishes in \~0.2 s but Hyper-V's demand metric updates on a multi-second
  cadence, so only a sustained load registers the true working set.
- **Cold boot → parser READY: 34.5 s** (the `health_timeout_s = 120` cold-boot
  budget covers it comfortably).
- **Memory:** the balloon engages \~60 s after boot and reclaims `MemoryAssigned`
  from the 1 GB startup down to the **512 MB floor**, held through both burst and
  idle-settle. Idle demand **\~199 MB**; **sustained-load peak demand \~256 MB** —
  both far below the 512 MB floor, so assigned floats at 512 MB regardless of the
  2 GB max. **Reclaim ≈ 2048 → 512 MB = \~1.5 GB** returned to the host.
- **Throughput / correctness:** **195 near-cap parses in 60 s, 0 failures**
  (no OOM, fail-closed never tripped). Near-cap 248,096 B → status `clean`,
  0.222 s, 223,974 chars out. Real fixture (`news_quantum.html`, 2,885 B) →
  `clean`, 0.014 s.
- **Sizing conclusion:** peak demand (256 MB) sits well below the 512 MB floor,
  so the 2 GB max is a ceiling never touched — it costs zero committed RAM while
  leaving spike headroom — though the hot-add path that headroom relies on was not
  exercised here (see NOT measured). The approved config is optimal; no tightening
  warranted. `vm_manager` only start/stops the VM, so the `Set-VMMemory`
  definition persists across launches.
- **NOT measured:** adversarial / pathological lxml structures (deep nesting,
  entity bombs) — only typical-large prose at the channel cap; co-resident cost
  with the host Qwen3-14B + VLM + voice loaded (parser measured in isolation);
  in-guest process RSS (host MemoryDemand used as the proxy); spread across
  multiple cold boots (n=1 boot, n=195 parses); and — the load-bearing one —
  **hot-add growth above the 1 GB startup toward the 2 GB max**, never exercised
  here because demand never reached even the 512 MB floor (peak 256 MB, \~half the
  floor, by deliberate headroom choice). The ceiling's protective value therefore
  rests on the *assumed* `hv_balloon` hot-add path (the reclaim/shrink direction
  IS proven, 1024 → 512 MB; the grow direction is not), not a measured one.

Machine-readable: `docs/performance/guest_parser_memory_2026-06-13.json` (+ raw
`.jsonl` samples).

---

### 2026-06-11 — First live ingest+retrieval on the merged knowledge bank: /ingest 1.1s, /approve 1.2s, grounded answer 64.3s (n=1 live verify, #655)

Timings from the **on-box live verify** of the just-merged UC-002/003 program —
a single production-posture pass (`dev_mode=False`, signed manifests verified at
boot, mTLS `CERT_REQUIRED`, real data root), NOT a benchmark; n=1, recorded
because they are the first-ever measured numbers for the ingest arc and the
first knowledge-grounded retrieval on this hardware.

- **Hardware/stack:** Arc 140V (driver 32.0.101.8826), Core Ultra 7 258V,
  OpenVINO 2026.1.0 / GenAI 2026.1.0.0, Qwen3-14B INT4 + pruned-6L INT8 draft.
- **Boot:** shared pipeline **145.3s** — a cold recompile (the 2026-05-28 GPU
  driver update invalidated the 2026-05-22 `ov_cache`; the warm-cache number
  elsewhere in this log does not apply to the first post-driver-update boot).
  PA measured boot 10.5s, AO 14.4s, VM start 18.1s (zero-NIC verified).
- **Ingest arc** (the staged 92,152-byte UniFi article, file mode): `/ingest`
  round-trip **1.14s** (clean, confidence 1.00, 666 words), `/approve` **1.21s**
  (3 chunks indexed). Retrieval question over the bank: first token **24.5s**,
  total **64.3s**, 64 frames, PGOV approved, answer correctly grounded.
- **NOT measured:** statistical spread (n=1); warm-cache boot under this
  driver; retrieval vs bank size (bank held 1 doc); paste/URL modes;
  concurrent load.

Machine-readable: `docs/performance/live_verify_ingest_2026-06-11.json`.
Functional evidence (audit chain PASS, labels-only stubs, #657 VM-stop verify):
Vikunja #655 + the gitignored
`docs/handoffs/uc002-003-live-verify-evidence_2026-06-11.md`.

---

### 2026-06-10 — Cleaner v1 `clean_html`: \~15 ms per 7-fixture corpus pass, CPU-only (UC-003, #655)

First performance record for the UC-003 Cleaner v1 extraction pipeline
(`services/cleaner/src/pipeline.py` `clean_html`: trafilatura `bare_extraction`
with metadata, favor_recall off, comments off → NFC/control/zero-width
normalization → injection scan + delimiter strip → verdict). The pipeline is
**CPU-only — no model, GPU not used** — so these numbers are independent of the
Qwen3-14B residency question (co-resident cost deliberately not measured, named
below).

- **Hardware:** Intel Core Ultra 7 258V (Lunar Lake), Windows 11 (26200),
  Python 3.11.9. **Stack:** trafilatura 2.1.0, lxml 6.1.1, cleaner 1.0.0.
- **Methodology:** `services/cleaner/tests/perf_capture.py` — the committed
  7-fixture synthesized corpus (`services/cleaner/tests/fixtures/`, 1,410–2,862
  raw bytes each), 3 warmup passes then 20 measured corpus passes
  (`time.perf_counter`) on the otherwise-idle dev box.
- **Corpus pass (all 7 fixtures):** mean **14.94 ms**, median 14.88 ms, stdev
  3.34 ms, min 10.47 ms, max 22.43 ms. Per-fixture means cluster at **1.9–2.4
  ms** (blog_code 1.90, news_quantum 2.07, paywall_teaser 2.37).
- **Real-page validation (separate record,
  `docs/performance/cleaner_realpage_validation_2026-06-10.md`):** the
  BleepingComputer UniFi-OS-root-bug article — 92,152 raw bytes → 666 clean
  words (4.86% retention), confidence 1.0, correct title/byline/date; the
  trailing sponsored block survives extraction (content-quality residual,
  #658 item 1).
- **NOT measured** (named per the testing-data-capture rule): real-world
  fetched 50–500 KB pages at scale (corpus is synthesized — re-measure at fetch
  activation); the `clean_text` paste path; lxml/trafilatura memory footprint;
  co-resident cost with the 14B on GPU/RAM; throughput under the ADR-030 §3
  guest-homed (Hyper-V VM) topology — these numbers are host-side, and Stage C
  moves fetched-HTML parsing into the NIC-less guest.

Machine-readable dataset: `docs/performance/cleaner_pipeline_2026-06-10.json`.

---

### 2026-06-08 — Sprint 18: model-loaded round-trip latencies (production-posture gateway→AO, IPC-routing, router-in-turn)

First **agent-run** measurements of the FULL gateway→AO chain with the real
Qwen3-14B loaded — distinct from the in-process `generate_text` harness
(2026-06-04 entry): C1 crosses a real socket under **production mTLS**
(`dev_mode=False`, signed-manifest boot) and runs the real PGOV output validation.
Captured under the #629 automate-first reframe — the agent ran every tier on the
dev box, no operator terminal time (Sprint 18 C1/C2/C3; Vikunja #631). The
machine-readable record is
`docs/performance/sprint18_model_loaded_roundtrip_2026-06-08.json`.

**Hardware:** Intel Core Ultra 7 258V (Lunar Lake); Arc 140V (Xe2) iGPU, 16 GB,
**driver 32.0.101.8826** (2026-05-28); 31.323 GB shared ceiling. **OpenVINO:**
2026.1.0; **GenAI:** 2026.1.0.0; **tokenizers:** 2026.1.0.0. **Model:** Qwen3-14B
INT4 (`openvino_model.bin` 8.03 GB) + Qwen3-0.6B pruned-6L INT8 draft (spec-decode
on) + bge-small-en-v1.5 ONNX-FP16 router (CPU). **Method:** single cold run per
tier (n=1), tiers run one-at-a-time in separate processes (one 14B in VRAM at a
time, no co-residency), machine otherwise idle, launcher not running. Each tier
recompiled the 14B cold (`LOCALAPPDATA` redirected to a temp dir → no warm
ov-cache).

| Tier | Path measured | Result |
|---|---|---|
| C1 (GAP-5) | gateway(mTLS) → real AO (mTLS, `dev_mode=False`, signed-manifest boot) → Qwen3-14B → PGOV → STREAM_TOKEN | load **18 413 ms**; first-token **3 101 ms**; total-turn **3 591 ms**; PGOV approved; 36-char reply |
| C2 (GAP-6) | gateway → real AO (model-loaded) → port resolution + STREAM_TOKEN, no misroute | total-turn **2 973 ms**; 36-char reply; no "Unsupported message type" |
| C3 (GAP-8) | real bge-small `classify()` + real AO turn (sprint12 module) | classify **6.4 ms** (intent CONVERSATIONAL, conf 0.592); AO turn 35 frames / **4 912 ms** |

**What the numbers say:** cold **model load (18.4 s) still dominates** the wait —
consistent with the 2026-06-04 cold load (19.3 s); the keep-warm/eviction lever is
unchanged. C1's first-token (3.10 s) exceeds the in-process `generate_text`
first-token (1.50 s, 2026-06-04) because this is the full cross-socket production
path cold (mTLS handshake + PGOV pass layered on generation). C1/C2 total-turn
reads *low* only because the benign single-sentence prompt produced a 36-char reply
(short generation), not because the path is faster — latency here is
load+path-bound, not content-bound. The router `classify` (6.4 ms) tracks the
2026-06-04 standalone (5.06 ms). The production-posture round-trip **works
end-to-end, automation-verified** — the point of the sprint.

**Not measured:** warm first-token (every tier recompiled cold); sustained
per-token throughput; co-resident peak; multi-run variance (**n=1 per tier** —
path-verification latencies, not a throughput benchmark); subjective answer
quality; AF_HYPERV (vsock) transport (tiers use AF_INET loopback — only the socket
family differs; the mTLS code path is the production one).

---

### 2026-06-06 — AES-256-GCM substrate encryption overhead: \~0.1ms per query, 1.5ms boot-cache (Sprint 14 EA-3)

**Date:** 2026-06-06
**Triggered by:** Sprint 14 EA-3 — substrate.db at-rest encryption wiring (ADR-025 criterion #5)
**Raw data:** `docs/performance/benchmark_2026-06-06_02-15-23.json`

#### What was measured

The CPU-side cryptographic overhead added to `SubstrateStore` by at-rest field encryption
(Sprint 14, ADR-025). This is a **CPU-only measurement** — the Arc 140V GPU is not involved in
AES-256-GCM operations (Lunar Lake has hardware AES-NI for these). Two costs were measured
**separately**, per the ADR-025 §3 criterion:

**(a) One-time boot/unlock embedding-cache decrypt:** at store construction, all 107 encrypted
embeddings are decrypted from disk into the in-RAM vector cache. This is paid once at unlock; every
subsequent vector search runs over the plaintext in-memory matrix.

**(b) Per-query matched-text decrypt:** each `retrieve()` call embeds the query, runs cosine over
the in-RAM cache (same path as the unencrypted store), then decrypts only the top-k matched
``text`` fields (AES-256-GCM, typically 4–6 fields per query).

#### Config stamp

| Field | Value |
|-------|-------|
| CPU | Intel Core Ultra 7 258V (Lunar Lake) |
| GPU | Intel Arc 140V — **NOT used** (AES-NI on CPU, not GPU) |
| Python | 3.11.9 |
| `cryptography` | 46.0.5 (AES-256-GCM + HKDF-SHA256) |
| Fixture | \~107 chunks synthetic (50 doc + 57 turns); fake bag-of-words embedder |
| Queries | 6 representative memory-style queries |

#### Results — pre-encryption baseline (SubstrateStore, plaintext)

| Metric | Value |
|--------|-------|
| retrieve() median | 0.397 ms |
| retrieve() mean | 0.435 ms |
| n_samples | 60 |

#### Results — encrypted (EncryptedSubstrateStore, AES-256-GCM)

| Metric | Value |
|--------|-------|
| Boot-cache decrypt (107 embeddings, one-time) | 1.45 ms mean, 0.014 ms/embedding |
| retrieve() median | 0.521 ms |
| retrieve() mean | 0.528 ms |
| retrieve() P95 | 0.648 ms |
| **Delta vs baseline (median)** | **+0.124 ms** |
| **Delta vs baseline (mean)** | **+0.093 ms** |
| n_samples (retrieval) | 120 |

#### Not measured

- GPU/OpenVINO 14B inference (not on this path)
- Real bge-small-en-v1.5 ONNX embedder load (fake embedder used to isolate crypto overhead)
- Memory footprint of the in-RAM embedding cache (\~164 KB for 107 × 384 × float32)
- Disk I/O timing for the SQLite file open itself

#### Interpretation

The boot-cache decrypt (1.45 ms for 107 embeddings) is negligible vs. LLM model load (\~10 s).
At 10k embeddings the projection is \~130 ms — still well under 1 s. The per-query overhead of
\~0.1 ms is immaterial relative to TTFT (\~940 ms measured on this hardware at spec-decode on).
The encrypted-at-rest + plaintext-in-RAM design (decrypt embeddings once at boot, search over
plaintext, decrypt only top-k text on retrieval) provides full at-rest protection — including
closing the embedding-inversion/vec2text semantic-shadow leak — at essentially zero runtime cost.

---

### 2026-06-05 — Spec-decode survives 16K now: the March "acceptance dies at ≥16K" finding is stale

**Why this run:** DEC-03 locked the context window at 16,384 tokens, and one of its
supporting findings (Task 4.3, 2026-03-03) was that speculative-decode acceptance
collapsed to **0.000 at ≥16K** — used to argue 16K was "fast enough" because spec-decode
was inert there anyway. That measurement predates two May changes: the ISS-1 fix
(2026-05-21, `num_assistant_tokens` → per-request `GenerationConfig`) and the draft swap
(2026-05-22, Qwen3-0.6B INT4 28L → **Qwen3-0.6B-pruned-6L INT8**), plus OpenVINO 2026.0 →
2026.1. So the "spec-decode is dead at 16K" claim was re-measured before being trusted.

**Hardware:** Intel Core Ultra 7 258V (Lunar Lake) + Arc 140V (Xe2) iGPU, 31.323 GB shared ceiling.
**Stack:** OpenVINO 2026.1 / GenAI, Qwen3-14B INT4 (target, GPU) + Qwen3-0.6B-pruned-6L INT8 (draft, GPU), `SchedulerConfig.cache_size = 3` GB, NAT = 3 (locked DEC-01), FP16.
**Method:** 2 warmup (discarded) + 4 measured generations per band, `MAX_NEW_TOKENS = 128`, greedy; long padded prompts at 3 context bands. Acceptance is the real `m_batch_sizes` rate, not a proxy. Reuses the March measurement functions verbatim (`scripts/recheck_specdecode_16k.py` loads `run_p5_task4_3_nat_sweep.py` by path). Data: `docs/performance/specdecode_16k_recheck_2026-06-05_07-12-46.json`.

| Context (actual tokens) | Acceptance (aggregate) | Combined TPS | Peak RSS |
|---|---|---|---|
| 2K (2067) | 0.472 | 12.21 | 12,713 MB |
| 8K (8211) | 0.575 | 9.56 | 12,713 MB |
| **16K (16403)** | **0.457** | **4.94** | 12,715 MB |

**Verdict:** Speculative decoding **does not collapse at 16K** with the current draft — acceptance holds **\~46–57%** across all bands (vs **0.000** at 16K in March). At 16K, throughput is **4.94 TPS — \~2.3× the \~2.13 TPS** Task 4.3 recorded. So 16K now delivers *both* the memory headroom DEC-03 was chosen for *and* a working spec-decode speedup — strictly better than the locked record implied. **DEC-03 (16K) stands, reaffirmed on current data.**

**Two caveats surfaced:**
1. **Footprint grew:** peak RSS at 16K is now **\~12.7 GB** (vs 3,562 MB in March — OV 2026.1 + INT8-draft accounting differs). Still within the 15,507 MB AO budget, but headroom is far tighter than March showed.
2. **The "20K is safe" March conclusion is now suspect** — at 12.7 GB already at 16K, 20K's footprint must be re-verified before assuming it fits. Not pursued (16K is the locked, sufficient choice).

**Not measured:** the 20K band, NAT values other than 3, co-resident cost (PA + Substrate loaded), end-to-end TTFT under the real UI path. Single-session GPU, no other model co-resident during the run.

---

### 2026-06-04 — Substrate (USE-CASE-002): embedder load attribution + per-turn retrieval

The two costs the Personal Knowledge Substrate adds to the Assistant Orchestrator,
against a **fresh temp substrate** (never the real `%LOCALAPPDATA%\BlarAI\substrate.db`).
Answers Vikunja #542 (benchmark startup + retrieval) and resolves #553 (the reported
"5–8 s embedder first-prompt tax"). Reproduce with `pytest -m hardware tests/substrate_benchmark`
(writes a community-grade JSON to `docs/performance/harness_substrate_use_case_002_*.json`).

**Hardware:** Intel Core Ultra 7 258V (Lunar Lake); bge-small-en-v1.5 ONNX FP16 on
**CPU** (ONNX Runtime) — the 14B GPU path is not exercised, so this never contends
with GPU work. **OpenVINO:** 2026.1.0-21367. **Driver:** *(fill from dxdiag)*.
**Method:** offline/air-gapped (`HF_HUB_OFFLINE`); embedder load decomposed by mirroring
`LeakageDetector.load_model`, measured *isolated* (transformers not pre-imported) vs
*marginal* (already imported, as in the real AO where `gpu_inference` imports it at
module load for the 14B); retrieval = `store.retrieve` (1 query embed + brute-force
cosine over doc+turn matrices), 8 representative prompts ×5 per scale, fresh temp
substrate per scale.

Embedder load (CPU, one run):

| Phase | ms |
|---|---|
| `import transformers` (AutoTokenizer) | 4 737 |
| ORT InferenceSession construct (graph-opt) | 232 |
| import onnxruntime | 160 |
| tokenizer files (`from_pretrained`) | 44 |
| first-inference warmup | 4 |
| **isolated total** | **5 177** |
| **marginal total** (transformers already imported) | **295** |

Per-turn retrieval:

| Corpus | p50 | p95 | mean | p95 as % of \~0.8 s first-token |
|---|---|---|---|---|
| 100 chunks | 5.1 ms | 6.2 ms | 5.3 ms | \~0.8% |
| 1 000 chunks | 9.0 ms | 10.7 ms | 9.2 ms | \~1.3% |
| 5 000 chunks | 26.3 ms | 28.4 ms | 26.6 ms | \~3.5% |

**Reading:** the "5–8 s embedder first-prompt tax" (#553) is \~92% the one-time
`transformers` import, which the 14B path (`gpu_inference`, module-level import via
`entrypoint.py:45`) already pays at boot before the Substrate builds. The embedder's
marginal load in the running AO is **\~0.3 s**, paid at boot inside the 4.6 s
AO-entrypoint slice (see the 2026-06-03 boot-attribution entry, #546). There is no
separate first-prompt tax — #546 measured the embedder *isolated*, where nothing
pre-imports transformers. **#553 closes as no-op (premise invalid).** Per-turn
retrieval is **immaterial to TTFT** (\~0.8–1.3% at realistic single-user scale, <5%
even at 5 000 chunks; against a \~0.8 s measured first-token latency — standard-decoding TTFT \~0.77 s, spec-on streaming TTFT reported n/a, cold spec-on first-token \~1.5 s, see the harness chat entry below) — no retrieval-optimization
follow-up; the brute-force cosine holds well past realistic scale.

**Not measured:** real-AO end-to-end boot+first-prompt trace with the 14B on the GPU
(avoided to not contend with the parallel security session); co-resident memory cost;
true cold-disk (post-reboot) transformers import (measured warm-disk — the import
varied 4.8–8.5 s across runs under system load, while the marginal load stayed
\~0.3–0.4 s); GPU driver version; ingest latency (corpus setup, not the measured path).

---

### 2026-06-04 — Headless harness: real-model component latencies (router / VLM / chat)

First measurements from the headless scenario + latency harness (`tests/harness`,
Vikunja #563) — the component latencies for the three model paths a user waits
on, captured **in-process on the real models with no GUI**. Distinct from the
full-boot `benchmark_gpu_inference.py` series: each scenario isolates a single
model path, so cold-load cost is visible and attributable rather than folded into
a boot total. Reproduce with `python -m tests.harness` (writes a community-grade
JSON per scenario to `docs/performance/harness_*.json`).

**Hardware:** Intel Core Ultra 7 258V (Lunar Lake); Arc 140V (Xe2) iGPU; 31.323 GB
shared ceiling. **OpenVINO:** 2026.1.0-21367; **GenAI:** 2026.1.0.0-2957.
**Driver:** *(fill from dxdiag / Device Manager)*. **Method:** single cold run per
scenario, run one at a time (no co-residency), machine otherwise idle with the
BlarAI launcher not running.

| Scenario | Model / precision | Device | Measurement | Result |
|----------|-------------------|--------|-------------|--------|
| router | bge-small-en-v1.5 / ONNX-FP16 | CPU | `classify()` per query (n=5) | mean **5.06 ms**, p50 4.98, p95 5.77, max 5.79; cold load 8 913 ms |
| vlm | Qwen3-VL-8B-Instruct / INT4 | GPU | lazy load + `describe_image` (128 tok) | **21 746 ms** (≈13 s load + ≈8 s inference); 659-char description |
| chat | Qwen3-14B / INT4 (spec-decode on) | GPU | `generate_text` (64 tok), cold first turn | first-token **1 500 ms**; total 6 123 ms (engine) / 6 138 ms wall; cold load 19 333 ms |

**What the numbers say:** the image and chat waits are dominated by **cold model
load** (\~13 s VLM, \~19 s 14B), not the pipeline — exactly the lever the keep-warm /
eviction follow-up (ADR-015 / Vikunja #550) and the VLM-memory options (#565)
target. The freeze the User-Operator hit on 2026-06-03 was those seconds running
*on the event loop*; the harness's Layer A regression lock now keeps them off it.

**Not measured:** co-resident peak (VLM + 14B together on the ceiling); warm
first-token (KV-cache hot); sustained per-token throughput; GPU driver version;
subjective answer quality. The VLM ran on a synthetic 512×384 image — its latency
is load + generation-bound, not content-bound, so a real photo of similar pixel
count measures the same (large-photo cost is the separate #565 input-size finding).

---

### 2026-06-03 — TPM 2.0 signing latency (Policy Agent JWT key rotation, Tier-0)

Not an inference benchmark — hardware-crypto latency for the Tier-0 security
hardening that moves the Policy Agent's JWT signing key into the platform TPM
(non-exportable; ADR-018 trust root). Recorded because it governs the runtime
cost of every authorization decision, and because the User-Operator (rightly)
asked whether it would bloat startup — answered with the instrument, not inference.

**Hardware:** Intel Core Ultra 7 258V (Lunar Lake); active TPM 2.0 = STMicroelectronics,
via the Windows CNG *Microsoft Platform Crypto Provider* (Pluton present but not the
active TPM; ISS-4 / `docs/TPM_CAPABILITY_FINDINGS.md`).
**Method:** `shared.security.tpm_signer` on the real chip, single-session, otherwise-idle.
ECDSA P-256 (ES256), \~126-byte signing-input. provision/export = 1 run; key_exists = 10;
sign = 30. `python -c` probe, `time.perf_counter()`.

| Operation | When | median | mean | min–max |
|---|---|---|---|---|
| provision (`ensure_key`) | once / ceremony | 247.5 ms | — | — |
| `export_public_key_pem` | once / ceremony | 146.0 ms | — | — |
| `key_exists` | per boot (at most) | 3.25 ms | — | –6.81 ms |
| **`sign` (one JWT)** | **per authorization (runtime)** | **93.6 ms** | 88.4 ms | 78.1–111.5 ms |

**Reading:** boot impact is \~3 ms (a key-existence check) — the 14B GPU compile (13.5 s,
53% of boot; see the boot-attribution entry below) dwarfs it, so startup is unaffected.
The real cost is \~94 ms per minted token at runtime — \~900× software ES256 (\~0.1 ms),
which is the price of a key that never leaves the chip — comfortably under the ≤750 ms
human-approval budget. Only a concern under high-frequency *autonomous* actioning; a
tiered signing path (software for low-sensitivity, TPM for sensitive) is the lever if so.

**Not measured:** TPM latency under concurrent/co-resident load; cross-boot variance;
other TPM vendors (this is one ST unit). TPM crypto is not GPU-style thermally sensitive,
so single-session sampling is representative here.

---

### 2026-06-03 — Full-boot attribution + Whisper compile-cache evaluation (#546)

Profiled the whole startup to name where the time goes, and evaluated caching the
Whisper compile specifically (the lever the voice handoff flagged after #545
killed the 14B cache). Intel Arc 140V (Xe2) / Core Ultra 7 258V, OpenVINO
2026.1.0, openvino-genai 2026.1.0.0. Boot slices parsed from `launcher.log` (two
consecutive warm-disk WinUI boots, current HEAD); Whisper cache from five
fresh-process loads (harness + raw JSON: `docs/performance/whisper_cache_probe_2026-06-03/`).

**Full-boot attribution** (admin-check → "launching WinUI app", warm disk):

| Slice | Time | Share |
|-------|-----:|------:|
| Hyper-V VM start | 1.2 s | 5% |
| Shared LLMPipeline compile (14B INT4 + 0.6B draft) | 13.7 s | 53% |
| Policy Agent measured-boot gate | 3.7 s | 14% |
| Assistant Orchestrator entrypoint | 4.6 s | 18% |
| Session DB + transport gateway + handshake | \~0.0 s | <1% |
| Voice engine (Whisper + Kokoro) | 2.6 s | 10% |
| **Total → WinUI app launch** | **\~25.8 s** | |

Boot is **compile-dominated**: the 14B+draft GPU compile is 53% of it. #545 already
established that compile is not cacheable for a net win (9 GB blob, cold read ≈
fresh compile once integrity-hashed). A second consecutive boot measured \~26.8 s —
same shape. **Honesty:** these are *warm-disk* boots (weights already in the OS
page cache from earlier in the day); a cold first-boot reads \~8.7 GB from cold
disk and will be slower on the compile slice. The operator's perceived "30–40 s"
also includes the WinUI app's own init (XAML / WinAppSDK) *after* the launcher
hands off — not in `launcher.log`, not measured here.

**Whisper compile-cache** (five fresh processes; only variable is `CACHE_DIR`):

| run | mode | load |
|-----|------|-----:|
| prod1 / prod2 | no cache (fresh compile) | 1.71 / 1.72 s |
| cold | cache (compile + write 496 MB) | 1.99 s |
| warm1 / warm2 | cache (read) | 0.75 / 0.76 s |

Fresh compile 1.72 s; warm read 0.75 s; + the mandatory integrity-hash of the
496 MB blob 0.29 s → warm total **1.04 s vs 1.72 s fresh = net save \~0.67 s**. So
unlike the 14B, caching Whisper *does* net a small positive — but it is \~0.67 s on
a \~26 s boot (≈2.6%), Whisper being only \~10% of boot, at the cost of a permanent
496 MB blob that must be recompiled+rewritten on any OpenVINO / driver / model
change. **Output identity was NOT verified** — the synthetic-audio transcription
probe failed (`skip:Runtime`), so warm-cache-vs-fresh transcript equivalence (the
byte-identity #545 required before trusting a cache) is unproven for Whisper.
Whisper fresh-compile here is **1.72 s**, not the 5.87 s logged 2026-06-02 (a
cold-GPU/cold-disk first load) — itself a warm-vs-cold reminder.

**Substrate embedder (bge-small-en-v1.5 ONNX, CPU):** previously unmeasured (#542).
Standalone load **5.0–8.1 s** (warm/cold disk, two fresh processes). The boot
AO-entrypoint slice (4.6 s) is *shorter* than this, indicating the embedder loads
**lazily on first prompt**, not at boot — a \~5–8 s first-prompt latency cost,
outside the \~26 s boot budget. (Inferred from the timing gap; pinning the exact
load point would need step instrumentation.)

**Decision (governance default — keep `CACHE_DIR=""` for Whisper):** the \~0.67 s
net win is imperceptible against a \~26 s boot, costs 496 MB + a cache-invalidation
maintenance surface, and rests on unverified output identity. Not worth enabling.
The real startup lever remains the 14B compile (53%), already settled. Path-not-
taken: a future GO would need (a) boot speed to become a real priority and (b)
output identity verified byte-for-byte first. See BUILD_JOURNAL 2026-06-03. Vikunja #546.

### 2026-06-03 — Vision: Qwen3-VL-8B-Instruct INT4 image understanding (ADR-015 MVP)

First measurements of the vision pipeline wired this session (image → VLM description
→ grounds the 14B). Target hardware: Intel Arc 140V (Xe2) / Core Ultra 7 258V,
OpenVINO 2026.1.0, openvino-genai 2026.1.0.0.

**Model:** `OpenVINO/Qwen3-VL-8B-Instruct-int4-ov` via `openvino_genai.VLMPipeline`,
device GPU. (The only INT4 OV-org Qwen3-VL — 4B/2B int4-ov repos do not exist.)

| Stage | Measurement | Notes |
|-------|-------------|-------|
| VLMPipeline load (GPU, cold) | **12.9 s** | one-time; pipeline cached after first image |
| Image describe (120 new tokens, 1 image @ 1600×2560) | **16.2 s** | greedy; standalone probe |
| End-to-end `load_document` (image → 256-token description) | **\~30 s** | first image (load + describe) |

**Measured STANDALONE — the 14B was NOT co-resident.** The load-bearing number for
trend analysis is therefore **UNMEASURED**: VLM + 14B (\~5 GB + \~8.7 GB) on the
31.3 GB shared ceiling — load/inference cost with both resident, and whether it OOMs
(fail-soft falls back to a placeholder; load-on-demand 14B eviction is the planned
mitigation — ADR-015 / Vikunja #550). **A future entry must measure co-resident vision.**

**Live-verified** in BlarAI 2026-06-03 (accurate description of a real photo).

### 2026-06-03 — GPU compile-cache (`CACHE_DIR`) cold/warm + numeric-identity probe

Re-opened the `CACHE_DIR=""` choice (`docs/governance/gpu-runtime.md:99-102`)
after the OpenVINO 2026.2 notes advertised faster GPU loads via cache blobs
(voice handoff §7.1, Vikunja #545). Measured on AC, standalone PowerShell (VS
Code closed), Intel Arc 140V / Core Ultra 7 258V, OpenVINO 2026.1.0,
openvino-genai 2026.1.0.0. Five fresh-process builds of the production shared
pipeline (Qwen3-14B INT4 target + 0.6B-pruned-6L INT8 draft; LATENCY / f16 /
SDPA-ON / MODEL_PRIORITY=HIGH; scheduler cache_size=3 + prefix_caching ON;
spec-decode `num_assistant_tokens=3`) — the only variable across runs is
`CACHE_DIR`. Greedy generation (`do_sample=False`), 3 version-controlled prompts,
128 max tokens. Raw artifacts + harness: `docs/performance/cache_dir_probe_2026-06-03/`.

| run | `CACHE_DIR` | pipeline load | note |
|-----|-----------|---------------|------|
| prod1 | `""` (production) | **11.15 s** | fresh compile |
| prod2 | `""` (production) | **10.44 s** | fresh compile |
| cold  | temp (empty) | **53.08 s** | compile + writes 9.0 GB blob (86 files) |
| warm1 | temp (populated) | **11.83 s** | reads 9.0 GB blob, OS file-cache cold |
| warm2 | temp (populated) | **6.90 s** | reads 9.0 GB blob, OS file-cache warm |

**Numeric identity — output byte-identical across all 5 runs** (SHA-256 per
prompt: `31aa8e96…`, `36130b57…`, `e04e04a7…`). Run-to-run determinism,
fresh-vs-warm identity, cold-vs-warm identity, warm stability — all hold. The
cache does NOT change generated output.

**Startup — no reliable win.** prod (fresh) mean 10.80 s; warm mean 9.36 s (raw
−1.44 s / −13%). That 13% is an OS-page-cache artifact: warm2's 6.90 s only
happened because warm1 had just pulled the 9 GB blob into RAM. warm1 — the
realistic first read from cold disk — was 11.83 s, \~1 s **slower** than a fresh
compile. On a real post-reboot launch the blob is not RAM-resident, so the
representative warm load (\~12 s) does not beat the \~11 s fresh compile. Enabling
the cache costs a one-time **+42 s** blob write, **+9.0 GB disk** per {OV version,
device, model, shape} key, and a re-write on every OV upgrade / driver update /
model swap.

**Reframe of the \~30–40 s startup:** the 14B+draft compile is only \~11 s of it;
the rest is Whisper-small load (5.87 s, see the 2026-06-02 entry) + Kokoro +
service/pipe bring-up + Substrate embedder. The compile cache addresses only the
\~11 s model slice and saves \~0 of it — a red herring for total startup. A future
entry should profile full boot and test caching **Whisper** (a much smaller blob).

**Decision status:** evidence only — the `CACHE_DIR` governance re-decision is the
User-Operator's (pending at time of writing). Recommendation on record: keep
`CACHE_DIR=""` (outcome unchanged) but correct the gpu-runtime.md rationale —
"guaranteed identical compiled state" is empirically unfounded (the cache *is*
identical); the real reason to stay disabled is "no startup win at a 9 GB / +42 s
cost on this hardware."

### 2026-06-02 — Voice pipeline (Whisper-small STT + Kokoro-82M TTS), ADR-017

Component latencies measured on the target hardware (Intel Arc 140V / Core Ultra
7 258V, OpenVINO 2026.1.0, openvino-genai 2026.1.0.0) during the voice-phase
feasibility probe. STT runs on the GPU; TTS runs on CPU (this venv's onnxruntime
exposes no GPU execution provider — see ADR-017 §2.3).

| Stage | Measurement | Notes |
|-------|-------------|-------|
| Whisper-small load (GPU) | **5.87 s** | one-time at surface startup; fail-soft |
| Whisper-small transcribe | **0.53 s** | for a 2.67 s utterance; exact round-trip |
| Kokoro-82M load (CPU) | **0.89 s** | one-time at surface startup; fail-soft |
| Kokoro-82M synthesis | **0.90 s** for 3.01 s audio | real-time-factor **0.30** (\~3.3× faster than playback) |
| Kokoro streaming first-chunk | **1.42 s** | first sentence of a multi-sentence reply |

**Derived first-spoken-token budget ≈ 2.6 s** (Whisper 0.53 + Qwen3 TTFT \~0.7
from the 14B entries below + Kokoro first-chunk \~1.4) — inside the <3 s target.

**Measurement honesty / still pending live:** the figures above are component
timings from synthetic audio (TTS→STT round-trip), not an end-to-end live-mic
turn. The true "stop speaking → first spoken word" latency through a live
microphone capture and a real Qwen3-14B reply is a hardware live-verify the
User-Operator still owes (Vikunja #539); it will replace this derived estimate
when read off the screen.

**Substrate (USE-CASE-002) cost is UNMEASURED — flagged.** The persistent
semantic memory added in Phase 5 incurs a startup embedder load and a per-prompt
retrieval cost that have never been benchmarked. This is a known gap: a future
entry should measure embedder load time and per-turn retrieval latency so the
Substrate's contribution to TTFT is on the record rather than assumed-negligible.

### 2026-05-22 — OpenVINO 2026.1.0 upgrade

**Date:** 2026-05-22
**Triggered by:** OpenVINO 2026.0 → 2026.1.0 package upgrade (openvino, openvino-genai, openvino-tokenizers).
**Benchmark script version:** `scripts/benchmark_gpu_inference.py` (prompt-set v1)
**Runs per config:** 5 measured + 2 warmup, 90 s cooldown between configs
**Raw data:** `docs/performance/benchmark_2026-05-22_00-07-31.json`

#### Config stamp

| Field | Value |
|-------|-------|
| Model | `Qwen3-14B`, INT4, GPU (Intel Arc 140V) |
| OpenVINO version | 2026.1.0-21367-63e31528c62-releases/2026/1 |
| openvino-genai version | 2026.1.0.0-2957-1dabb8c2255 |
| GPU driver version | 32.0.101.8424 (2026-01-05) |
| num_assistant_tokens | 3 |
| Draft model | `qwen3-0.6b` INT4 |

#### Results — standard decoding (spec-off; `speculative_decoding_achieved: false`)

| Metric | mean | median | P95 |
|--------|------|--------|-----|
| Throughput (tok/s) | 9.8 | 10.6 | 11.5 |
| TTFT (ms) | 774 | 771 | 787 |
| Total latency (ms) | 8576 | 5549 | 22108 |

Model load time: 12452 ms · 20 generations, 0 errors · incremental streaming: yes

#### Results — speculative decoding (spec-on; `speculative_decoding_achieved: true`)

| Metric | mean | median | P95 |
|--------|------|--------|-----|
| Throughput (tok/s) | 12.6 | 13.6 | 16.8 |
| TTFT (ms) | n/a | n/a | n/a |
| Total latency (ms) | 6932 | 5711 | 15121 |

Model load time: 12179 ms · 20 generations, 0 errors · incremental streaming: **no**

**Notes**

*OpenVINO upgraded 2026.0.0 → 2026.1.0* (current stable) and **kept** after empirical evaluation.

*Versus the 2026.0 entry below:* standard decoding is **identical** (10.6 tok/s median both); speculative decoding is **marginally better** — mean 12.6 vs 11.9, median 13.6 vs 13.2, and notably more consistent run-to-run. Roughly 3–6 % on the speculative config — not a big gain, but a real one with no downside.

*Answer quality verified identical to 2026.0* — `check_speculative_quality.py` produced byte-identical answers across five prompts (factual, arithmetic, explanatory, creative). The 2026.1 release-notes accuracy concern for Qwen3-family models on Core Ultra 200V / Arc integrated GPUs did **not** materialize for Qwen3-14B INT4.

*Test suite green on 2026.1:* 1093 passed, 0 failed.

*Streaming under speculative decoding is still absent* — unchanged from 2026.0; inherent to the speculative / ContinuousBatching backend, not a 2026.1 regression.

---

### 2026-05-21 — Speculative decoding fixed and measured (standard vs speculative)

**Date:** 2026-05-21
**Triggered by:** The speculative-decoding fix (`b699ad1`) — first measurement where speculative decoding actually engages — measured with the thermally-fair benchmark (`fd854f4`).
**Benchmark script version:** `scripts/benchmark_gpu_inference.py` (prompt-set v1)
**Runs per config:** 5 measured + 2 warmup, 90 s cooldown between configs
**Raw data:** `docs/performance/benchmark_2026-05-21_23-44-08.json`

#### Config stamp

| Field | Value |
|-------|-------|
| Model | `Qwen3-14B`, INT4, GPU (Intel Arc 140V) |
| OpenVINO version | 2026.0.0-20965-c6d6a13a886-releases/2026/0 |
| openvino-genai version | 2026.0.0.0-2820-dab5b993a38 |
| GPU driver version | 32.0.101.8424 (2026-01-05) |
| num_assistant_tokens | 3 |
| Draft model | `qwen3-0.6b` INT4 |

#### Results — standard decoding (spec-off; `speculative_decoding_achieved: false`)

| Metric | mean | median | P95 |
|--------|------|--------|-----|
| Throughput (tok/s) | 9.9 | 10.6 | 11.5 |
| TTFT (ms) | 762 | 761 | 777 |
| Total latency (ms) | 8578 | 5549 | 22043 |

Model load time: 13379 ms · 20 generations, 0 errors · incremental streaming: yes

#### Results — speculative decoding (spec-on; `speculative_decoding_achieved: true`)

| Metric | mean | median | P95 |
|--------|------|--------|-----|
| Throughput (tok/s) | 11.9 | 13.2 | 16.6 |
| TTFT (ms) | n/a | n/a | n/a |
| Total latency (ms) | 7202 | 6206 | 15391 |

Model load time: 13708 ms · 20 generations, 0 errors · incremental streaming: **no**

**Notes**

*Speculative decoding now engages* (`achieved: true`) for the first time — it was silently falling back to standard decoding before the fix `b699ad1`. This is the first valid spec-off vs spec-on comparison.

*Speedup: \~1.25x median, \~1.45x on long generations.* The 252-token prompt went 11.4 → 16.5 tok/s, with total latency 22.0 s → 15.3 s. Short generations benefit less, and the trivial 8-token prompt is marginally *slower* under speculative decoding (the per-step draft+verify overhead is not amortised over so few tokens). For substantive conversational answers — the case that matters — it is a clear win.

*An earlier "\~2x" figure was an overstatement.* It compared a cool-GPU speculative run against a thermally-disadvantaged baseline. This entry — measured with the thermal cooldown — is the methodology-corrected figure: \~1.4x.

*Live token streaming does NOT occur under speculative decoding.* The stream callback never fires on the speculative / ContinuousBatching backend, so TTFT is unmeasurable here and the response is delivered all-at-once rather than token-by-token. Standard decoding streams normally (TTFT \~760 ms). This is a UX trade-off; whether it is fixable is being investigated.

*Standard-decoding throughput here (median 10.6) is higher than the initial-baseline entry (8.0).* The initial baseline was measured on an already-warm GPU; this run's pre-run idle plus the cooldown make this the more accurate standard-decoding figure.

---

### 2026-05-21 — Initial baseline (standard INT4 decoding)

**Date:** 2026-05-21
**Triggered by:** Initial baseline — first recorded measurement. Establishes the reference point before any speculative-decoding, EAGLE-3, OpenVINO, or driver change.
**Benchmark script version:** `scripts/benchmark_gpu_inference.py` (prompt-set v1)
**Runs per config:** 5 measured + 2 warmup
**Raw data:** `docs/performance/benchmark_2026-05-21_22-01-40.json`

#### Config stamp

| Field | Value |
|-------|-------|
| Model | `Qwen3-14B` |
| Quantization | INT4 |
| Device / GPU | Intel Arc 140V GPU (16 GB) — integrated, Core Ultra 7 258V "Lunar Lake" |
| OpenVINO version | 2026.0.0-20965-c6d6a13a886-releases/2026/0 |
| openvino-genai version | 2026.0.0.0-2820-dab5b993a38 |
| GPU driver version | 32.0.101.8424 (2026-01-05) |
| num_assistant_tokens | 3 |
| Draft model | `qwen3-0.6b` INT4 (present on disk) |

#### Results — standard decoding (config: spec-off; `speculative_decoding_achieved: false`)

| Metric | mean | median | P95 |
|--------|------|--------|-----|
| Throughput (tok/s) | 7.6 | 8.0 | 9.2 |
| TTFT (ms) | 947 | 937 | 1077 |
| Total latency (ms) | 11424 | 7276 | 31138 |

Model load time: 10410 ms · 20 generations, 0 errors

#### Results — speculative decoding requested (config: spec-on; `speculative_decoding_achieved: false` — **fell back to standard**)

| Metric | mean | median | P95 |
|--------|------|--------|-----|
| Throughput (tok/s) | 6.3 | 6.8 | 7.3 |
| TTFT (ms) | 1129 | 1116 | 1205 |
| Total latency (ms) | 13652 | 8834 | 35117 |

Model load time: 12296 ms · 20 generations, 0 errors

**Notes**

*Finding 1 — speculative decoding does not engage on this stack.* Both configs ran **standard decoding**. The spec-on config tried to construct the speculative pipeline and OpenVINO threw `Option not found: num_assistant_tokens` (`runtime/plugin_config.hpp:214`); the engine caught it and fell back. So the two result blocks above are the *same* engine path measured twice — not an A/B of speculative vs standard. This confirms empirically that BlarAI currently runs standard decoding only, despite `speculative_decoding_enabled = true` in config and the `qwen3-0.6b` draft model being present on disk. Fixing this is the next performance task.

*Finding 2 — thermal throttling under sustained load.* Throughput falls monotonically run-over-run within a config. Standard decoding, the 252-token prompt: run 1 = 9.4 tok/s → run 5 = 8.1 tok/s, with TTFT climbing in step. The Arc 140V is an integrated GPU in a thin laptop; sustained generation heats it and it clocks down. A separate cool-GPU smoke run (1 pass, no warmup) hit 11.5 tok/s on the same prompt — the cold-start ceiling, \~40 % above the warmed-up steady state.

*Why "spec-on" reads \~16 % slower.* It is **not** a config effect — speculative decoding never engaged. The benchmark runs spec-off then spec-on back-to-back with no cooldown, so the spec-on block always measures an already-hot GPU. The gap is the thermal-ordering artifact of Finding 2, nothing more.

*Methodology limitation (carry-forward).* Until speculative decoding actually engages, the spec-off / spec-on columns are not a real comparison; and even once it does, the back-to-back ordering needs a cooldown (or a cold per-config process) before the A/B is trustworthy. **The reference number to track from this entry is the standard-decoding column: \~8 tok/s median throughput, \~940 ms median TTFT.**

---

### 2026-06-05 — Sprint 14 EA-4: sessions.db at-rest encryption overhead (AES-256-GCM field cipher)

**Date:** 2026-06-05
**Triggered by:** Sprint 14 EA-4 — sessions.db content-bearing columns (`turns.content`, `sessions.title`) encrypted at rest via AES-256-GCM field cipher (ADR-025). Addendum per CLAUDE.md Testing-Data-Capture requirement.
**Hardware:** Intel Core Ultra 7 258V (Lunar Lake), Arc 140V GPU, 32 GB LPDDR5X (31.3 GB usable)
**Python runtime:** CPython 3.11.9 (venv), `cryptography` package (PyCA), AES-256-GCM via `cryptography.hazmat.primitives.ciphers.aead.AESGCM`
**Measurement methodology:** Pure CPU microbenchmark. `time.perf_counter()` wrapping cipher calls, 1000 iterations per cell for single-field overhead, 200 iterations for `list_sessions`, 500 for `get_session_turns`. No co-resident inference load. SQLite file on local NTFS (temp dir).

**Not measured:** GPU inference co-residence cost; disk I/O (SQLite page cache warm); DEK unsealing latency at process start (single-call cost, not per-operation).

#### Single-field AES-GCM overhead (SoftwareSealer / same CPU path as TpmSealer-unsealed cipher)

| Field | Plaintext size | Encrypt median | Encrypt P95 | Decrypt median | Decrypt P95 |
|-------|---------------|----------------|-------------|----------------|-------------|
| `turns.content` (short) | 25 B | 0.8 µs | 0.9 µs | 0.7 µs | 0.8 µs |
| `turns.content` (medium) | 137 B | 0.8 µs | 0.9 µs | 0.7 µs | 0.8 µs |
| `turns.content` (long) | 963 B | 1.0 µs | 1.2 µs | 0.9 µs | 1.0 µs |
| `sessions.title` | 55 B | 0.8 µs | 0.9 µs | 0.7 µs | 0.8 µs |

AES-GCM is throughput-dominant for short fields; single-call latency is dominated by nonce generation and HMAC overhead, not data length.  Sub-microsecond decrypts up to \~1 KB.

#### List and turn-fetch overhead (encrypted vs. plaintext store, 50 sessions / 10 turns)

| Operation | Encrypted store | Plaintext store | Overhead |
|-----------|----------------|-----------------|----------|
| `list_sessions` (50 sessions) | 0.19 ms median, 0.20 ms P95 | 0.09 ms median, 0.10 ms P95 | +0.10 ms (2.1x SQL baseline) |
| `get_session_turns` (10 turns) | 0.048 ms median, 0.053 ms P95 | not measured separately | — |

The 2x overhead on `list_sessions` is expected: 50 AES-GCM decrypts (one per title, \~0.7 µs each) plus unchanged SQLite query cost. Absolute latency (0.19 ms) is imperceptible in any UX context — the LLM response dominates by 3–5 orders of magnitude.

**Notes:** The encryption overhead is noise relative to the GPU inference loop (\~1–8 s per turn). No performance concern for BlarAI's current usage profile (single user, interactive). Community-grade note for OpenVINO ecosystem: this measures only app-layer Python/PyCA overhead — the Intel AES-NI hardware path is used transparently by `cryptography`.

---

### [TEMPLATE — do not use as real data]

> **How to read this section:** this is a formatting template only.
> Every metric value below is a placeholder. The first real entry appears
> after the baseline benchmark is actually executed on hardware.

**Date:** YYYY-MM-DD
**Triggered by:** (e.g., "initial baseline", "OpenVINO 2025.x upgrade", "EAGLE3 integration")
**Benchmark script version:** `scripts/benchmark_gpu_inference.py` (prompt-set version embedded in script)

#### Config stamp

| Field | Value |
|-------|-------|
| Model | `Qwen3-14B` |
| Model dir | `models/qwen3-14b/openvino-int4-gpu` |
| Quantization | INT4 |
| Device | GPU |
| OpenVINO version | X.Y.Z |
| openvino-genai version | X.Y.Z |
| num_assistant_tokens | 3 |
| Draft model dir | `models/qwen3-0.6b/openvino-int4-gpu` |
| Driver version | *(fill manually)* |

#### Results — speculative decoding OFF (achieved: off)

| Metric | mean | median | P95 |
|--------|------|--------|-----|
| Throughput (tok/s) | XX.X | XX.X | XX.X |
| TTFT (ms) | XXXX | XXXX | XXXX |
| Total latency (ms) | XXXX | XXXX | XXXX |

Model load time: XXXX ms

#### Results — speculative decoding ON (achieved: on / off)

| Metric | mean | median | P95 |
|--------|------|--------|-----|
| Throughput (tok/s) | XX.X | XX.X | XX.X |
| TTFT (ms) | XXXX | XXXX | XXXX |
| Total latency (ms) | XXXX | XXXX | XXXX |

Model load time: XXXX ms

**Notes:** *(optional — anything surprising, e.g., first-run compilation overhead, GPU contention)*

---

*Entries above this line are real benchmark results. Entries below are older.*

<!-- First real entry will be pasted here after baseline run -->
