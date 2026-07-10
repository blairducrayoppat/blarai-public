# DRAFT — openvino.genai feature-request issue
# Review before posting. Target repo: openvinotoolkit/openvino.genai (Issues)
# Do NOT post code; this is a demand-signal + test-bed offer that references the
# existing (stale-closed) PR #3209 as prior art.
# Tracked: Vikunja #710 (OSS Contributions). Companion decision record in that task.

---

**Title:** [Feature Request] Revive persistent KV-cache dump/restore to disk (PR #3209) for prefix reuse in long-context / agentic GenAI

**Labels (suggest):** feature, GPU, performance, continuous batching

---

## Summary

Please consider reviving and upstreaming **persistent (disk-backed) KV-cache dump/restore** for the GenAI `ContinuousBatchingPipeline`, so the KV cache for a *fixed prompt prefix* (system prompt + tool schemas + earlier conversation turns) can be saved once and restored on a later run, instead of being recomputed by a full prefill on every fresh session.

A complete, tested implementation already existed in **#3209 ("KV cache dump/restore to disk for GPU acceleration")** — `kv_cache_dump_dir` / `kv_cache_load_dir` knobs, block-manager disk I/O, and 11 tests, reporting "up to 12× faster" for long-context. It was **closed by the stale-bot for inactivity on 2026-04-27 with no maintainer review** — i.e. it lapsed, it was not rejected on technical grounds. This request is to bring that capability back (revive #3209, or guidance on adopting/rebasing it).

## Status re-verification (2026-07-05)

A trusted-source research pass re-confirmed the gap as of **OpenVINO 2026.2.1**: no disk-backed / cross-process KV persistence exists or appears on the official roadmap. What does exist: in-memory prefix caching (process-lifetime only), KV-cache *eviction* + SnapKV (which shrink the cache, they do not persist it), and 2026.1's KV-cache reporting metrics (observability only). Adjacent-but-different: model_server PR #4332 (idle-unload / transparent lazy reload) frees GPU memory but does **not** preserve KV across the unload — which strengthens this request's case: today there is no way to keep prefix state across any residency change. Sources: model_server release notes 2025.3–2026.2.1; openvino.genai KV-eviction/SnapKV docs; model_server PR #4332 / issue #4141.

## Motivation — long-context agentic inference on a constrained integrated GPU

I run a local, long-context, tool-calling assistant on an **Intel Core Ultra 7 258V (Lunar Lake) with the Arc 140V (Xe2) iGPU and 32 GB unified LPDDR5X** via OpenVINO GenAI (dense Qwen3-class model, INT4 weights, on GPU).

In an agentic loop the model re-ingests a large, *mostly stable* context every turn: system prompt + tool definitions + accumulated history. On this device that prefill is the dominant latency — a **cold ~32K-token prefill costs ~176 s on the Arc 140V iGPU** (measured; intrinsic O(n²) attention cost, not eviction thrash). Today that cost is paid again from scratch on every new session, because in-memory prefix caching (`enable_prefix_caching`) only survives within a single process lifetime.

Persisting the stable-prefix KV to disk and restoring it on the next launch would amortize that prefill across sessions — turning a ~3-minute cold start into a bounded disk read. On an integrated GPU the trade is strongly favorable: re-reading a few GB of KV from NVMe (~GB/s) is far cheaper than recomputing a 32K prefill.

A second motivating workload has since landed on the same box: a **model-swap coding dispatch** — a 14B planner and a 30B coder share the one iGPU, one resident at a time, swapping per job. Every coder swap-in starts a cold prefill of a large, byte-stable task preamble (tool schemas, project scaffold contract, seeded acceptance tests), and in-memory prefix caching cannot help because the swap tears the process down by necessity (the two models cannot co-reside in 31.3 GB shared memory). Persistent KV would amortize that repeated preamble across residencies — precisely the dump-at-unload / restore-at-load shape #3209 implemented.

## Why this is feasible / standard practice

Disk- and CPU-tiered KV-cache offloading with cross-process/cross-session reuse is established production technique in the broader ecosystem:
- **LMCache** — persistent, tiered KV offload (CPU/disk/remote), reuse across requests, sessions, and engine instances.
- **vLLM production-stack** — KV-cache offloading via LMCache.
- **llm-d** — native KV-cache offloading to any filesystem.

So this is a feature-completeness gap in OpenVINO GenAI, not a research question — and #3209 already demonstrated a working OpenVINO implementation.

## Scope / correctness notes (to pre-empt the obvious concerns)

- Restored KV is valid only for an **identical (model build + inference precision + KV-cache precision/quant config + exact prefix token sequence)**. The natural cache key is a hash over those. A mismatch must fall back to normal prefill, not produce silent garbage.
- Useful specifically for **long, stable prefixes** (system + tools + history); short prompts won't benefit and need no special handling.
- KV-cache-precision / quantization settings must be captured in the key so a dump made at one precision is never restored at another.

## What I can contribute

I can provide a reproducible **Arc 140V (258V, Lunar Lake) long-context benchmark** — cold-prefill vs. restore-from-disk wall-clock across context lengths — and validate a revived implementation on this hardware. I'm an OpenVINO community contributor and happy to act as a test bed for the integrated-GPU / unified-memory path specifically, and to publish the measured numbers.

## Questions for maintainers

1. Was there any known technical blocker to #3209, or did it simply lapse?
2. Is reviving #3209 the preferred path, or is persistent KV reuse expected to arrive via a different mechanism (e.g. an LMCache-style connector)?
3. Is there appetite for a `dump_dir`/`load_dir`-style API on `ContinuousBatchingPipeline` (and ideally surfaced through the higher-level `LLMPipeline`)?

Prior art: #3209.
