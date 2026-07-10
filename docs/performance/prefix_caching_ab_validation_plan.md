# Prefix-Caching A/B Re-Validation Plan (`enable_prefix_caching`)

**Status:** PLAN — review before executing. No production config change until the evidence supports it.
**Date:** 2026-06-30
**Device:** Intel Core Ultra 7 258V (Lunar Lake) / Arc 140V (Xe2) iGPU / 32 GB unified LPDDR5X. OpenVINO GenAI 2026.2.1.
**Tracked:** Vikunja (BlarAI Core Development).

## Why this exists

`enable_prefix_caching` is **already ON in production** — hardcoded `True` at `launcher/__main__.py:1542`, locked per **ADR-012 Amendment 3** on the strength of two numbers ("~23% higher TPS, halves TTFT, no spec-decode AR collapse"). That lock never tested the angles that could make prefix caching a *bad* trade on a memory-constrained iGPU. This plan re-validates the ON decision on **current** OpenVINO + current workloads, from multiple angles, so the decision rests on full evidence — not one happy-path measurement. Possible outcomes: keep ON, turn OFF, or make it **workload-conditional**.

## Harness

Standalone A/B modeled on `scripts/benchmark_kv_cache_sweep.py` (schema v2): fresh pipeline per (flag × scenario) combo with `del`/`gc`/settle; **flip `enable_prefix_caching` instead of pinning it** (`build_shared_pipeline(..., enable_prefix_caching=False|True)`). No launcher edit needed for the benchmark.

- **Methodology:** N ≥ 5 timed runs + ≥2 warmup discarded; report median + std + p95. Streamer-callback TTFT (as in the kv-sweep harness). Fixed, version-controlled prompt sets.
- **Pipeline config = production:** INT4 14B on GPU, FP16 inference hint, spec-decode ON (Qwen3-0.6B draft, `num_assistant_tokens` per-request), `cache_size = 3 GB` as shipped. Run a **spec-OFF control** and an **optional right-sized `cache_size` control** (to isolate the caching engine from the 3 GB starvation effect found in #709) — and state which in every result.
- **Memory introspection:** `core.get_property("GPU", "GPU_MEMORY_STATISTICS")` (`cl_mem` ≈ reserved KV pool, `usm_host` ≈ weights/working) + `psutil` system-available delta vs the 31.323 GB ceiling + the analytical KV ground-truth (`analytical_kv_gib`).
- **HONEST CAVEAT (carries from #709):** the reserved KV pool is fixed at `cache_size` regardless of cache hits, so host/GPU memory readouts are **largely blind to prefix-cache *hit* savings**. The primary observable for the caching win is **TTFT/throughput** (a hit skips re-prefill), not a memory delta. The plan measures memory to catch *pressure/regression*, not to "see" the win.

## Scenarios (each run OFF vs ON)

| # | Scenario | What it probes | Primary metrics |
|---|----------|----------------|-----------------|
| S1 | **Shared-prefix repeated turns** — fixed ~2–4K-token system+tools prefix, then N distinct short user queries reusing it | The claimed win; confirm/refute +23% TPS / ½ TTFT on current OV | TTFT (cold 1st vs warm Nth), decode tok/s, total latency |
| S2 | **Realistic agentic multi-turn** — fixed system+tools, history GROWS each turn, short tool-call-style outputs, ~10 turns | The actual target use case (not synthetic repeats) | per-turn TTFT trend, cumulative session latency |
| S3 | **No-reuse worst case** — every prompt fully unique (nonce prefix) | Overhead/regression when caching CAN'T help | TTFT, decode tok/s ON vs OFF (look for ON < OFF) |
| S4 | **Long context (16K = `max_context_tokens`)** at `cache_size=3` | Interaction with the starved 3 GB pool (#709) at length | TTFT, recompute/eviction events, errors |
| S5 | **Spec-decode acceptance** | Re-verify the lock's "no AR collapse" claim | acceptance %, spec speedup ON vs OFF |
| S6 | **Correctness / determinism** — same prompt set, temp=0 | Prefix caching must NOT change outputs | exact output-token equality ON vs OFF |
| S7 | **Co-resident pressure (optional)** — 14B + SDXL paired | Does ON change footprint vs the 31.3 GB ceiling? | `cl_mem`/`usm_host`, system-avail headroom |

## Decision criteria (set before running, to avoid post-hoc rationalizing)

- **Keep ON** iff: S1/S2 show a real net TTFT/throughput win on current OV **AND** S6 shows no output drift **AND** S5 shows no acceptance collapse **AND** S3/S4 show no material regression.
- **Turn OFF (or make conditional)** if: S3 regresses materially (overhead with no reuse), or S4 worsens long-context, or S6 shows output drift, or S7 erodes ceiling headroom.
- **Workload-conditional** is a valid outcome: e.g. ON for AO conversational (high prefix reuse), OFF for PA classification (already runs `False`) or for long-context turns. Record the rule, not just a global flag.

## Outputs (community-grade, per the testing-data mandate)

- Machine-readable `docs/performance/prefix_caching_ab_<ovver>_<ts>.json` (per-scenario OFF/ON medians + std + p95 + memory).
- `PERFORMANCE_LOG.md` narrative entry with the decision and the evidence behind it.
- If the result overturns or refines ADR-012 Am.3 → an ADR amendment + `BUILD_JOURNAL.md` entry.

## Next step after plan approval

Build the standalone harness (fork `benchmark_kv_cache_sweep.py`, flip the flag, add the S1–S7 prompt builders), dry-run S1/S3 to validate the rig, then the full matrix on the Arc 140V.
