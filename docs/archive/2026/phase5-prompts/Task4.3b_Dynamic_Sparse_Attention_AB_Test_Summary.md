---
title: Task4.3b_Dynamic_Sparse_Attention_AB_Test_Summary
status: archived
area: portfolio
---

# Task 4.3b — Dynamic Sparse Attention A/B Test

**Execution Prompt:** `docs/Task4.3b_v1.xml`
**Branch:** TBD
**Pre-condition:** Task 4.3 COMPLETE

## Objective

A/B test dynamic sparse attention (TRISHAPE and XATTENTION modes) against dense attention baseline. Elevated to HIGH priority after Task 4.3 revealed AR=0.000 at ≥16K for all NAT values — sparse attention changes KV cache contents by evicting middle tokens, which could theoretically shift the AR collapse boundary.

- **Context bands:** [4096, 8192, 12288, 16384, 20480]
- **Modes tested:** Dense (baseline), TRISHAPE, XATTENTION
- **Workloads:** AO + Code Agent ONLY
- **PA excluded:** Security constraint — KV eviction with `num_retained_start_tokens_in_cache=128` would evict system prompt tokens 129–600 containing full classification rules

## API

```python
scheduler = SchedulerConfig()
scheduler.use_sparse_attention = True
scheduler.sparse_attention_config = SparseAttentionConfig()
scheduler.sparse_attention_config.mode = SparseAttentionMode.TRISHAPE
```

Confirmed available in OpenVINO 2026.0. Intel demonstrated 2.6× TTFT reduction at 32K on exact BlarAI hardware (Arc 140V, Qwen3-14B).

## Key Measurements

- TPS with sparse vs dense at each band
- Acceptance rate with sparse vs dense — specifically whether AR collapse point shifts from \~12K
- TTFT impact per band
- Peak RSS under sparse eviction
- Per-step acceptance rate arrays to detect if sparse changes the draft rejection pattern

## Disposition Logic

- If sparse attention shifts AR collapse boundary higher → directly informs DEC-01 (adaptive NAT), DEC-02 (speculative decoding collapse policy), DEC-03 (context cap)
- If no AR improvement → sparse attention evaluated purely on TTFT/TPS merit
- PA remains dense attention regardless of outcome

## Evidence Artifact

`phase2_gates/evidence/p5_task4_3b_sparse_attention_ab_test.json`
