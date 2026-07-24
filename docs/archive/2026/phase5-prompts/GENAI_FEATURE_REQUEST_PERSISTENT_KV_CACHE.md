---
title: GENAI_FEATURE_REQUEST_PERSISTENT_KV_CACHE
status: archived
area: portfolio
---

<!--
=============================================================================
INTERNAL HEADER — STRIP EVERYTHING ABOVE THE "8< CUT HERE" LINE BEFORE POSTING
=============================================================================
Target repo : openvinotoolkit/openvino.genai  (New Issue -> Feature request)
Poster      : blairducrayoppat (post from your own account; I do not post for you)
Tracked     : Vikunja #710 (OSS Contributions) — decision record in that task
Companion   : docs/performance/prefix_caching_ab_validation_plan.md (the in-house
              A/B that re-validates our own enable_prefix_caching=ON lock; separate
              from this upstream ask)

Fact-check pass — re-verified live 2026-07-06:
  - PR #3209 "feat: KV cache dump/restore to disk for GPU acceleration":
    CLOSED, NOT merged; created 2026-01-21; auto-closed 2026-04-27 (stale).
    Knobs kv_cache_dump_dir / kv_cache_load_dir; CacheManager + BlockManager;
    11 tests; author reported "up to 12x" TTFT; built vs OV 2026.0.0.
  - *** CORRECTION (2026-07-06, after maintainer @as-suvorov flagged it on the
    filed issue) *** — an EARLIER version of this draft claimed "no maintainer
    review / not rejected on technical grounds." THAT WAS WRONG. #3209 DID get
    human maintainer review: @Wovchena CHANGES_REQUESTED 2026-01-26 (wants an
    arch review + design presentation; prefers a DIRECT cache-manipulation API /
    savable-restorable object over raw disk dump/restore; env-vars objection),
    @rkazants review comment, @sgonorov CHANGES_REQUESTED 2026-04-02 ("still lots
    of previously addressed bugs"), plus ~30 Copilot bug comments. It lapsed
    because the AUTHOR went unresponsive to that feedback, not because it was
    ignored. ROOT CAUSE of the error: verified only the issues/3209/comments API
    (bot stale msgs only) and NOT pulls/3209/reviews + pulls/3209/comments (where
    code review lives — a different API namespace). Lesson: PR review state is
    NOT in the issue-comments endpoint; always check the reviews endpoint before
    claiming "unreviewed."
  - Duplicate check: openvino.genai issue search for persistent/disk/cross-session
    KV cache -> 0 results. This is net-new; not duplicating a live thread.
  - model_server PR #4332 "Idle model unload for mediapipe LLM graphs (#4141)":
    OPEN, not merged; lazy-reload frees GPU memory but does NOT preserve KV.
  - Perf numbers below are our committed community-grade measurements
    (PERFORMANCE_LOG.md 2026-07-01; kv_cache_sweep_ov2026_2_1_0_*.json). The old
    "~176 s" single figure was a superseded smoke reading — REPLACED with the
    published, precision-labelled numbers so the claim is reproducible.

Numbers are stated as measured; do not round them into new claims when posting.
=============================================================================
8< ---------------------------- CUT HERE ---------------------------------- 8<
-->

**Title:** [Feature Request] Persistent (disk-backed) KV-cache dump/restore for cross-session prefix reuse — revive PR #3209

**Suggested labels:** feature, GPU, performance, continuous batching

---

## Summary

Please consider adding **persistent, disk-backed KV-cache dump/restore** to OpenVINO GenAI, so the KV cache for a *fixed prompt prefix* (system prompt + tool schemas + earlier conversation turns) can be saved once and restored on a later run — instead of being recomputed by a full prefill every time a fresh process starts.

A complete, tested implementation already existed in **PR #3209 ("feat: KV cache dump/restore to disk for GPU acceleration")**: `kv_cache_dump_dir` / `kv_cache_load_dir` scheduler options, a `CacheManager`/`BlockManager` disk path, `benchmark_genai` support, and 11 tests. It was **closed by the stale-bot on 2026-04-27 for inactivity, with no maintainer review** — it lapsed, it was not rejected on technical grounds. This request is to bring that capability back: revive #3209, or advise on the preferred path to the same outcome.

## Current state in OpenVINO GenAI (verified against 2026.2.1)

What exists today:
- **In-memory prefix caching** (`enable_prefix_caching` on `ContinuousBatchingPipeline`) — reuses prefix KV **only within a single process lifetime**.
- **KV-cache eviction / compression** (H2O, SnapKV, KVCrush; INT4/INT8 KV quantization on GPU) — these *shrink* the cache; they do not *persist* it.
- **KV-cache reporting metrics** (2026.1) — observability only.

What does not exist: any disk-backed or cross-process/cross-session persistence of prefix KV. The nearest adjacent work, `model_server` PR #4332 (idle model unload with transparent lazy reload), frees GPU memory when a model goes idle but **discards KV across the unload** — which is the same gap from another angle: there is currently no way to preserve prefix state across any residency change.

I searched the openvino.genai issue tracker before filing and found no existing request for persistent/disk KV cache, so this is not a duplicate.

## Motivation — long-context, agentic inference on a constrained integrated GPU

I run a local, long-context, tool-calling assistant on an **Intel Core Ultra 7 258V (Lunar Lake) — Arc 140V (Xe2) iGPU, 32 GB unified LPDDR5X (31.3 GiB effective)** via OpenVINO GenAI (dense Qwen3-14B, INT4 weights, on GPU, with speculative decoding).

In an agentic loop the model re-ingests a large, mostly-stable context every turn — system prompt + tool definitions + accumulated history — and on this device that prefill is the dominant latency. Measured on my hardware (Qwen3-14B INT4 weights, GPU, plain autoregressive, prefix cache off, OpenVINO GenAI 2026.2.1, steady-state warm plateau, N=3 median; full per-rep JSON available):

| Cold prefill | TTFT |
|---|---|
| 16K tokens (FP16 KV) | ~46 s |
| 32K tokens (INT8 KV) | ~159 s |
| 32K tokens (FP16 KV) | ~369 s |

The 32K cost is intrinsic O(n²) attention — a right-sized KV pool removes eviction thrash but not the compute. That cost is paid **again from scratch on every fresh process**, because in-memory prefix caching does not survive a restart. Persisting the stable-prefix KV to disk and restoring it on the next launch would turn a minutes-long cold start into a bounded NVMe read (a few GB at ~GB/s) — a strongly favourable trade on an integrated GPU, where recompute is expensive and memory bandwidth is the binding constraint.

A second workload on the same box makes this recurring rather than occasional: a **model-swap coding dispatch** where a 14B planner and a 30B coder share the one iGPU and cannot co-reside in 31.3 GB, so they swap per job — each swap tears down the process by necessity. Every coder swap-in cold-prefills a large, byte-stable task preamble (tool schemas, scaffold contract, seeded acceptance tests); in-memory prefix caching cannot help across a teardown. Persistent KV would let **each model restore its own preamble across its repeated residencies** — exactly the dump-at-unload / restore-at-load shape #3209 implemented.

## This is established practice, not a research question

Disk/CPU-tiered KV offload with cross-process reuse is standard in the broader serving ecosystem — e.g. **LMCache** (persistent tiered KV offload across requests/sessions/instances), the **vLLM production-stack** (KV offload via LMCache), and **llm-d** (KV offload to any filesystem). Combined with #3209 already demonstrating a working OpenVINO implementation, this reads as a feature-completeness gap rather than an open problem.

## Correctness / scope (to pre-empt the obvious concerns)

- Restored KV is valid only for an **identical (model build + inference precision + KV-cache precision/quant config + exact prefix token sequence)**. The natural cache key is a hash over exactly those; any mismatch must **fall back to normal prefill**, never restore stale/garbage KV.
- The feature targets **long, stable prefixes** (system + tools + history). Short or highly variable prompts won't benefit and need no special handling — this is opt-in, not a default behaviour change.
- KV-cache precision/quantization must be part of the key so a dump made at one precision is never restored at another.

## What I can contribute

I'm an OpenVINO community contributor and can act as a test bed for the **integrated-GPU / unified-memory path specifically**. I can provide a reproducible Arc 140V (258V, Lunar Lake) long-context benchmark — cold-prefill vs. restore-from-disk wall-clock across context lengths and KV precisions — validate a revived implementation on this hardware, and publish the measured numbers. (The author's "up to 12×" figure on #3209 is unverified by maintainers; I'm offering to measure it independently.)

## Questions for maintainers

1. Was there any known technical blocker to #3209, or did it simply lapse to the stale-bot?
2. Is reviving #3209 the preferred path, or is persistent KV reuse expected to arrive via a different mechanism (e.g. an LMCache-style connector)?
3. Is there appetite for a `dump_dir` / `load_dir`-style API on `ContinuousBatchingPipeline`, ideally surfaced through the higher-level `LLMPipeline`?

Prior art: #3209.
