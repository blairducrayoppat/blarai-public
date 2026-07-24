# VLMPipeline Long-Context Decode Curve — Methodology (Qwen3.6-35B-A3B)

*Instrument: `scripts/benchmark_vlm_longcontext.py`. Tickets: #932 (consolidation
research — the "35B long-context decode curve" unknown) and #930 (consolidation).*

This note exists so a reviewer can judge the protocol **before any measured
number is trusted** — the standing bar for this project is that minting
methodology unreviewed fails the protocol bar. Read this, then read the script;
the script's module docstring carries the same protocol in code-adjacent form.

## 1. What question the instrument answers

For the natively-multimodal **Qwen3.6-35B-A3B** driven **text-only** through
OpenVINO GenAI's `VLMPipeline` on the Intel Arc 140V iGPU: **how do decode
throughput, prefill throughput, time-to-first-token (TTFT), and memory change as
the input context grows** from a short prompt up to a long one?

No existing instrument answers this for the `VLMPipeline` class:
`benchmark_vlm_text_inference.py` uses a fixed *short* prompt set, and
`kv_cache_sweep.py` sweeps context but on the `LLMPipeline` + KV-precision path
(the resident 14B), a different pipeline class.

## 2. Why the numbers are comparable to the short-context 35B bench

Comparability is engineered, not asserted. This harness **imports and reuses the
proven per-generation primitive** (`_measure_one`), its greedy
`GenerationConfig`, and the `compute_median` / `compute_mean` / `compute_p95`
statistics from `scripts/benchmark_vlm_text_inference.py`. Consequences:

- **Decode throughput** is defined identically: `generated_tokens / (total_latency
  − ttft)`, greedy (`do_sample=False`), `max_new_tokens = 256` (the short bench's
  value). The generation length and timing math are held constant.
- The **only axis that changes** band-to-band is the input prompt length.

A reviewer can therefore lay a long-context row beside a short-context 35B row
and read the decode falloff directly, with no re-basing.

## 3. Context bands and the caps that bound them

Default bands: **2 048 / 8 192 / 16 384 / 32 768** input tokens (a doubling
ladder). Two caps bound the ladder:

- **Trained context window** — `max_position_embeddings = 262 144` (256 K). All
  default bands sit far inside it, so the context window is **not** the binding
  cap on this box.
- **Memory ceiling** — the Arc 140V shares the **31.323 GiB** system RAM. This
  **is** the binding cap, enforced by the stop condition in §5.

## 4. Per-band metrics

| Metric | How it is obtained |
|---|---|
| Decode tok/s (median / mean / p95) | reused `_measure_one`, N measured runs after M warmup |
| Prefill "pp" tok/s | **derived at the band's own length**: `actual_input_tokens / ttft_seconds` — at long context the band prompt *is* the prefill workload |
| TTFT (ms) | reused `_measure_one` streamer first-token timestamp |
| Peak memory | **both** disciplines: system In-Use = `Total − min(Available)` (background sampler) **and** process RSS peak |
| Coherence | fixed "needle" fact at the context START, question at the END; full output text captured **for the reviewer to judge** |

Default cadence: **2 warmup + 5 measured** runs per band, 15 s cooldown between
measured runs (thermal settle). Greedy / deterministic throughout.

### Coherence probe (reviewer-judged, never script-scored)

Each band prompt is `preamble + planted-needle + neutral-filler + question`. The
needle plants a distinctive access code (`MERIDIAN-2718-ANCHOR`) near the start;
the trailing question asks the model to restate it and summarize. Only the middle
filler grows/shrinks to hit the band — the probe is otherwise identical across
bands. **Coherence is judged by the reviewer from the captured text**, matching
the short bench's stance on openvino.genai #3870. A `needle_recalled` boolean
rides along as a **supplementary, explicitly non-authoritative** deterministic
signal (`needle_recall_is_authoritative: false` in the JSON) — it is not a
quality gate and does not decide pass/fail.

## 5. The memory-ceiling stop condition (fail-closed, model-aware)

Before each band, the harness projects peak In-Use and **skips** (never thrashes)
a band that would breach the ceiling:

```
projected_peak = resident_after_load  +  analytical_KV(band)  +  working_margin (2.0 GiB)
skip band if  projected_peak > 31.323 − safety_margin (1.5 GiB)
```

`resident_after_load` is **measured** (`Total − Available` right after the load),
not assumed. Because both KV size and prompt length grow monotonically with the
band, the first breach stops the sweep; larger bands are recorded
`skipped_memory_ceiling_after_prior`.

**Critical model fact — the 35B is a HYBRID-attention MoE.** Its
`config.json → text_config.layer_types` shows only **10 of 40** layers are
`full_attention`; the other 30 are `linear_attention` (recurrent/SSM-style with a
**fixed** state that does **not** grow with context). The analytical KV term
counts **only the full-attention layers**:

```
KV bytes/token = full_attn_layers(10) × kv_heads(2) × head_dim(256) × 2 (K+V) × 2 bytes (FP16)
              = 20 480 bytes/token   →   0.625 GiB at 32 K,  ~5 GiB at the full 256 K
```

A naive "all 40 layers" projection would over-estimate KV by **~4×** and could
falsely skip a perfectly feasible 32 K band. The layer count is read from
`layer_types` at runtime, not hardcoded (fallback: total layer count — a
conservative over-estimate — only when `layer_types` is absent). The analytical
value is the **fail-closed pre-band guard only**; the live sampler records the
true peak.

## 6. Refuse-to-start guards

- **AC power** (fail-closed): a battery-only run is refused — thermal/clock
  variance would poison the curve.
- **GPU held** (#711 policy: fail loud, never queue): refuses to start if the AO
  loopback port (5001) responds or an OVMS fleet model server is alive.
- **Pre-load headroom**: refuses the ~19 GiB load if available RAM is below a
  22 GiB floor (a load transiently stages weights on CPU + GPU simultaneously;
  the 2026-06-21 lesson — check headroom *before* the load).

## 7. Output — community-grade JSON

Written to `docs/performance/vlm_longcontext_<model>_<timestamp>.json`, carrying:
hardware (CPU, GPU `FULL_DEVICE_NAME`, GPU driver, RAM), OpenVINO + GenAI
versions, commit SHA, box-state stamp (start + end, per #816), full model
geometry, the complete methodology block (bands / prompt construction / run
counts / metric definitions / the memory-stop condition), per-band measured
numbers, and an explicit **`not_measured`** list.

## 8. What is NOT measured (named, not hidden)

- Vision / image inputs (text-only probe).
- Speculative decoding (does not exist for the `VLMPipeline` class / this model
  family on OpenVINO GenAI).
- Co-resident cost (benchmarked alone, GPU free).
- KV-cache precision alternatives (FP16 default only — see `kv_cache_sweep.py`
  for that lever).
- Coherence/answer **quality as a scored metric** (captured for the reviewer; the
  needle flag is supplementary only).
- Context bands beyond the highest completed band (memory-ceiling stopped).
- Concurrent-request / batched throughput (single sequential request).

## 9. How the coordinator invokes it (GPU-serial, after review)

Runtime venv, BlarAI app closed / AO stopped, GPU free, `LOCALAPPDATA` redirected
if any pytest ran first, on AC power:

```
.venv\Scripts\python.exe scripts\benchmark_vlm_longcontext.py \
    --model-dir C:/Users/mrbla/models/qwen36-35b-a3b-int4-ov-OFFICIAL
```

Overrides: `--bands 2048,8192,16384,32768` · `--runs 5 --warmup 2` ·
`--cooldown 15`. The record then lands a dated narrative entry in
`PERFORMANCE_LOG.md` alongside the JSON, per the performance-capture mandate.
