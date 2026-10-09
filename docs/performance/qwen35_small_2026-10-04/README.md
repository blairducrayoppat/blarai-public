# Study 3 - Qwen3.5-4B INT8 with Multi-Token Prediction vs Qwen3-14B INT4 on an Arc 140V (2026-10-04)

One machine, one day, one contributor. Reference measurements offered so others can compare and correct;
please say where it is wrong.

## What this is

Whether Qwen3.5-4B (INT8, Intel's `OpenVINO/Qwen3.5-4B-int8-ov`, revision
`e4d8de7a25bc3007261c28785bc190c97cabd243`, which ships an `openvino_mtp_model` Multi-Token Prediction head)
can stand in for a Qwen3-14B INT4 + pruned-0.6B-draft speculative-decoding pipeline as a shared assistant and
policy-classifier brain. Speed, memory and task quality, with the instrument problems found on the way.

## Setup

- Intel Core Ultra 7 258V (Lunar Lake), Arc 140V iGPU, 31.32 GB LPDDR5X, Windows 11 Pro, AC power,
  High-performance plan, GPU driver 32.0.101.8831. Bitdefender on-access running; no OneDrive process in any
  sample. Booted 05:02:53 local, campaign window 05:43 to 11:03.
- Qwen3.5 arms: OpenVINO 2026.4.0-22959, GenAI 2026.4.0.0-3407, `ContinuousBatchingPipeline`, greedy,
  `max_num_seqs=1` (the default of 256 fails to allocate the linear-attention cache budget), 3 GB KV
  budget, `KV_CACHE_PRECISION=f16`, `DYNAMIC_QUANTIZATION_GROUP_SIZE=0`, `INFERENCE_PRECISION_HINT=f16`,
  `GPU_ENABLE_SDPA_OPTIMIZATION=ON`. MTP: `draft_model` pointing at the same directory,
  `num_assistant_tokens=3`, prefix caching off.
- 14B arm: OpenVINO 2026.2.1-21919 / GenAI 2026.2.1.0-3123 (as deployed) and, as a runtime control,
  2026.4.0. LLMPipeline + pruned Qwen3-0.6B INT8 draft, prefix caching on, KV precision left at default.

## Files

| file | contents |
|---|---|
| `speed_rows.csv` | every generation of the interleaved speed campaign (614 rows), thermal-stamped |
| `speed_visits.csv` | visit means, the unit of analysis |
| `multiturn_ttft_turns.csv` | live-history multi-turn first-token delay, 6 turns x 3 visits per arm |
| `quality_runs.csv`, `quality_cases.csv` | per suite and job pass/fail/skip counts, and per-case statuses |
| `conditions_summary.json` | continuous system sampler (CPU %, memory, thermal zone, Bitdefender/OneDrive presence) |
| `raw/` | raw invocation JSON, analysis summaries (including `speed_summary_strict_gate.json`, the sensitivity reading that also drops rows that started above 72 C), thermal-recovery and variance probes; case reports keep ids, statuses, expected labels, golden case descriptions and short labels (no generated text) |

## Findings (conditions and limits in `PERFORMANCE_LOG.md` of the BlarAI repository, entry 2026-10-04)

1. **Sustained decode throttles about 3x.** Same prompt back to back: 48 ms/token cold, about 160 ms/token after
   about two minutes (thermal zone 77 to 96 C). A fresh process started hot starts slow; 20 to 60 s of rest
   recovered it in 4 of 5 probes. The speed campaign therefore waits for the thermal zone to reach 72 C before
   every generation (COLD, primary) and records a plateau protocol separately. The wait loop's flag is the gate;
   the temperature read right before each generation can be higher (see the sensitivity under Finding 2).
2. **MTP on this iGPU is a real speed-up for the 4B**: cold decode 37.3 / 36.6 / 51.1 tok/s (838 in, 6076 in,
   43 in) with MTP against 20.3 / 19.9 / 20.8 without (1.84, 1.84, 2.46x), visit-mean CV 1.4 to 7.2 percent,
   n = 5 visits. 348 of 504 draft tokens accepted. **Sensitivity (added 2026-10-04 after the data was read,
   `raw/speed_summary_strict_gate.json`, `--strict-start-temp 72`):** the gate is the wait loop's flag, not the
   start temperature; 36 of the 69 cold rows (52 percent) started above 72 C (72.9 to 79.9 C, 5 above 76.9). Dropping them leaves 2 to 3 visits per 4B cell, and the
   ratios that still form are 1.84 (pa), 1.82 (ao-long) and 2.47 (t1) for MTP on over off, against 1.84, 1.84 and
   2.46 above; several 4B-over-14B ratios are no longer formed (n below 2 on a side; two 14B cells fall to n = 1). This differs from the sibling Arc 140T report
   (openvino #38153) at 9B INT4; different model, precision and part, so not a contradiction.
3. **Output bytes with and without MTP**: identical on 5 prompts of 16 to 48 generated tokens in every visit (speed campaign). ~~Across all 63 model calls of the agentic and conversation suites (pinned inputs) they were identical.~~ **Retracted 2026-10-04 (independent review of #1665, finding F2):** that count was V0 run 1 only. Recomputed 2026-10-04 over every pinned run that both the MTP-on and MTP-off arms have (agentic and conversation, V0 repeats 1 to 3 and the V1, V2 and V3 perturbations: 12 runs, 377 model calls): the prompts were identical in all 377 calls, and the outputs were identical in 376 and DIFFERENT in 1 (agentic V3 run 1, call 17 of 40: 448 characters with MTP, 442 without; the two outputs share their first 402 characters). The first figure checked V0 run 1 only (63 calls). Not investigated: why that call differs. `raw/compare_on_vs_off.json` is the V0-run-1-only file and is superseded by `raw/compare_4b_on_vs_off_recomputed.json`.
4. **The price of MTP**: it needs prefix caching off. Live six-turn conversation, first-token delay at turn 6
   (2362 input tokens): 4B + MTP 1588 ms, 4B without cache 1687 ms, 4B with prefix cache 784 ms, 14B with cache
   690 ms.
5. **Memory** (In-Use = Total - Available, peak minus idle): 4B +8.7 GB, 4B + MTP +9.7 GB, 14B +17.4 GB
   (2026.2.1) or +12.3 GB (2026.4).
6. **Quality** (greedy; 4B with and without MTP agree on every case): the 4B passes 33 of 35 policy
   classification cases against the 14B's 35; both ~~misses~~ cases are expected-DENY answered ALLOW,
   ~~byte-identical in 3 of 3 runs~~ parsed label and confidence identical in 3 of 3 runs (the raw text was not
   compared across runs; raw text was captured for one run). **Correction 2026-10-04:** in those two requests (`pa-mdl-007`, `pa-mdl-013`) the
   harmful `command` field is rejected by the Policy Agent's schema check, so no model is shown the command (a
   prompt with the command replaced by `echo ok` is byte-identical on all 13 model-mode cases for the 4B, 9B and
   14B); with the command made visible the 4B answers DENY, and the 14B answers DENY on the shipped prompt because
   of the rejection marker, so its 35 of 35 on these two cases is not evidence of understanding them. Table and
   rows: `qwen35_small_9b_2026-10-04/raw/pa_variants/` (Study 4). ~~Not checked: whether real requests carry commands
   under rejected fields.~~ **Checked from the code 2026-10-04 (round-2 review G1; static evidence, no runtime
   trace):** live tool calls carry their arguments under the key `args`, which the same validator rejects, and no
   production path was found that sends a request to the model-backed classifier (the orchestrator calls the
   deterministic rule checker in process); the 14B's reaction to the marker describes the evaluation prompt and
   is not shown to be the live path. Do not implement a deterministic DENY on schema rejection before the live
   request shapes are traced; see Study 4. On meaning-preserving prompt perturbations the 14B flipped 5 of 22 conversation cases and the
   4B none.

## Not measured

Sustained load beyond two minutes; GPU utilisation and clocks; output identity beyond 48 tokens and 5
prompts; the 2B, the 9B, INT4; a signed manifest for the 4B; answer-quality and preference-memory repeats
(one run per arm; flagged `single_run: true` in the quality summaries, so their `failing_in_every_run` lists are not repeated findings); ~~why the 4B misses the two classification cases~~ (explained 2026-10-04, see Finding 6).

## Method notes

Unit of analysis is the visit mean (one load of one arm, consecutive reps averaged). Prefix-cache arms'
first-token delay is reported from the cold protocol only (the plateau protocol repeats prompts they have
cached). A pre-registered minimum detectable effect (decode 5 percent, first-token 30 percent) and a ratio
refusal at CV > 15 percent were fixed before the campaign. Two instrument defects found by an independent
review are fixed in the shipped analysis scripts: a 14B label mismatch that silently dropped all 4B-vs-14B
ratios, and a whitespace perturbation erased by the Qwen3.5 chat template (the analysis now counts prompts
actually changed).

Generated with AI assistance (Claude Code); the measurements, commands and decisions are recorded in the
BlarAI repository under ticket #1663.

License: CC-BY-4.0, like the rest of this dataset.
