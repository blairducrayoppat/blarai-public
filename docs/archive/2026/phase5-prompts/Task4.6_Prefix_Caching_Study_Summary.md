---
title: Task4.6_Prefix_Caching_Study_Summary
status: archived
area: portfolio
---

# Task 4.6 — Prefix Caching Study

**Execution Prompt:** `docs/Task4.6_v1.xml`
**Branch:** `feature/p5-task4-6-prefix-cache`
**Pre-condition:** Task 4.5 COMPLETE (Context Band Extension)

## Objective

Measure the impact of `SchedulerConfig.enable_prefix_caching` on TTFT and TPS across production workload profiles. Prefix caching stores computed KV cache blocks for reusable prompt prefixes (system prompts, session history) so that repeated prefill of the same token sequence is skipped on subsequent requests.

- **Variable:** `enable_prefix_caching = True` vs `False` (baseline)
- **Scope:** All three workload profiles — PA (high-frequency short prompts with fixed system prompt), AO (session history grows but system prompt prefix is constant), Code Agent (large codebase context with stable preamble)
- **Construction-time parameter:** Requires pipeline recompilation per variant (not a per-request toggle)

## Key Measurements

- TTFT with and without prefix caching at each production band
- TPS with and without (should be unchanged — prefix caching affects prefill, not decode)
- Second-request TTFT (the reuse case — same prefix, different user message)
- Peak RSS delta (prefix cache consumes additional memory for stored KV blocks)

## Rationale for Position in Dependency Chain

Prefix caching operates on the prefill phase (KV cache population from input tokens). NAT sweep (Task 4.3) operates on the decode phase (token generation). These are independent variables — prefix caching produces identical KV cache contents, just faster. NAT results are valid regardless of prefix cache state. Prefix caching depends on Task 4.5 (context cap) because the cache memory budget varies with the allowed context window size.

## Evidence Artifact

`phase2_gates/evidence/p5_task4_6_prefix_cache_study.json`
