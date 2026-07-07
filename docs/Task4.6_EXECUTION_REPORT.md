# Task 4.6 Execution Report — Prefix Caching Study

**Branch:** `feature/p5-task4-6-prefix-cache`
**HEAD:** `304cfe5`
**Base:** `a7b0c2b` (main)
**Test baseline:** No unit tests added (benchmark-only task). Pre-existing 755/786 baseline unchanged.

**Disposition: SPEC_DECODE_INCOMPATIBLE**

## Files Changed (4)

1. **CREATE** `phase2_gates/scripts/run_p5_task4_6_prefix_cache.py` — crash-resilient benchmark harness
2. **CREATE** `phase2_gates/evidence/p5_task4_6_prefix_cache_study.json` — 24-record evidence artifact
3. **UPDATE** `docs/adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md` §2.2 — Pipeline kwargs row: EVALUATING → **LOCKED** (OFF)
4. **UPDATE** `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` — Entry 20

## Quality Gates (all 7 evaluated)

| Gate | Result |
|---|---|
| G-01 completeness | **PASS** — 24/24 records, all fields present |
| G-02 valid count | **PASS** — 8/8 groups with 3/3 valid |
| G-03 warm reduction | **MIXED** — PA 4K +7.6%, PA 12K +7.1%, AO 4K -4.2%, AO 12K +9.9% |
| G-04 PA budget | PA_WARM_HIGH — 12,139ms >> 1,500ms |
| G-05 AR preservation | **SPEC_DECODE_INTERACTION** — AR collapse at 12K warm calls |
| G-06 RSS impact | **PASS** — 75MB delta |
| G-07 memory budget | **PASS** — peak 12,950MB < 15,507MB |

## Critical Finding — AR Collapse with Prefix Caching

| Group | ON cold AR | ON warm-1 AR | ON warm-2 AR |
|---|---|---|---|
| PA 12K | 0.167 | 0.000 | 0.000 |
| AO 12K | 0.402 | **0.003** | **0.000** |

Prefix caching destroys speculative decoding acceptance rates on warm calls at 12K context. Cold AR is healthy, but warm AR collapses to near-zero. The modest TTFT warm reduction (5–10% in 3/4 groups) is rendered moot by the loss of speculative decoding throughput.

## Full TTFT Results

| Group | OFF cold (ms) | ON cold (ms) | ON warm-1 (ms) | ON reduction | Verdict |
|---|---|---|---|---|---|
| PA 4096 | 10,279 | 13,143 | 12,139 | +7.6% | MODEST_BENEFIT |
| PA 12288 | 55,790 | 49,519 | 46,005 | +7.1% | MODEST_BENEFIT |
| AO 4096 | 16,079 | 11,180 | 11,644 | -4.2% | NO_BENEFIT |
| AO 12288 | 66,787 | 50,485 | 45,462 | +9.9% | MODEST_BENEFIT |

## Calibration

CALIBRATION_WARNING (+42.4% vs Task 4.4 ref) — expected due to different `max_new_tokens` and system prompt between PA and AO profiles. Relative ON/OFF deltas within this run are valid.

## Compile Times

OFF=25,092ms, ON=16,716ms.

## ADR-012 §2.2 State After This Commit

Pipeline kwargs row is now **LOCKED** — `enable_prefix_caching` OFF for all profiles.

## Crash Resilience Note

Script resumed 3 Pipeline A groups from prior EA's partial JSON. OFF AO 12K re-measured fresh. Pipeline B completed in a single pass with no crashes.

## LEDGER

Entry 20 appended with full measurement tables and AR collapse documentation.

## Verification Commands

```powershell
git log --oneline -1
git diff HEAD~1 --name-only
```
