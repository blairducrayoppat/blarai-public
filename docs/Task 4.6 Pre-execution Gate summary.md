Task 4.6 Pre-Execution Gate Summary
1. Feature Under Test and What It Does
SchedulerConfig.enable_prefix_caching is a KV scheduler optimization in OpenVINO GenAI. When enabled, the scheduler stores computed KV attention activations for prompt tokens in a persistent cache. On a subsequent call whose input begins with the same leading token sequence (the common prefix — in BlarAI's case, the fixed system prompt), the model skips re-computing attention for those prefix tokens and reads their KV states from cache instead.

The expected benefit is a reduction in TTFT proportional to the fraction of the input occupied by the shared prefix. The benefit is prefill-phase only; decode-phase TPS is not expected to change.

Critical risk: Speculative decoding (which must remain enabled) involves a draft model KV cache that must be coordinated with prefix cache lookups. OpenVINO GenAI 2026.0 may not support this coordination fully, which could result in no benefit, increased latency, or AR collapse. This is the primary uncertainty this task resolves.

2. Two Profiles Under Test and Their System Prompt Strategies
Profile	System Prompt Strategy	max_new_tokens	Stop Tokens	Expected Prefix Fraction
PA (Policy Agent)	Classification instruction + /no_think. Estimated \~130 tokens. Fixed across all calls in a session.	32	[151645, 151668] (<|im_end|> + <|think|>)	4K: \~3.2% / 12K: \~1.1%
AO (Assistant Orchestrator)	Minimal conversational prompt + /no_think. Estimated \~30 tokens. Fixed per session.	128	[151645] (<|im_end|> only)	4K: \~0.75% / 12K: \~0.25%
Both profiles use the same system prompt text across all 3 sequential calls within a group, but vary user content per call (seeded CALL_1/2/3), ensuring only the system prompt constitutes the shared prefix.

Implication: The shared prefix fractions are small (<5% in all cases). Absolute TTFT savings will be modest in wall-clock terms. The task is measuring whether the feature is functional with speculative decoding active, and whether any measurable benefit exists as signal for Task 4.10's lock decision.

3. Test Matrix
Dimension	Values	Count
prefix_cache	OFF, ON	2
Profile	PA, AO	2
Context band	4,096, 12,288 tokens	2
Sequential calls per group	cold → warm-1 → warm-2	3
Total groups: 8 (2 cache settings × 2 profiles × 2 bands)
Total generate() calls: 48 (24 per pipeline setting)
Pipeline compilations: 2 (one per cache setting; profiles and bands share the same compiled pipeline)
Execution order: Pipeline A (OFF) compiles first, then runs all 4 groups [(PA, 4K), (PA, 12K), (AO, 4K), (AO, 12K)] consecutively with no interleaving. Calibration check is performed after Pipeline A completes. Pipeline A is fully saved before Pipeline B (ON) compiles. Same group order repeats for Pipeline B.

Critical sequencing constraint: All 3 calls within each group must run consecutively on the same pipeline instance with no intervening calls from other groups. Interleaving profiles would evict the prefix from cache.

Pipeline construction (both):
scheduler = ov_genai.SchedulerConfig()
scheduler.cache_size = 3
scheduler.enable_prefix_caching = False  # or True
pipeline = ov_genai.LLMPipeline(
    str(target_path), "GPU",
    scheduler_config=scheduler,
    draft_model=ov_genai.draft_model(str(draft_path), "GPU"),
    **{"GPU_ENABLE_SDPA_OPTIMIZATION": True},  # LOCKED Task 4.4
)
4. Primary Metric and Cold/Warm-1/Warm-2 TTFT Measurement
Primary metric: ttft_ms — first-token wall-clock time in milliseconds.

Source: output.extended_perf_metrics.get_ttft().mean from a pipeline.generate([prompt], gen_config, streamer) list-input call (bare-string input is forbidden — it returns no metrics).

Within each ON-pipeline group:

Cold (call 1): KV prefix cache is empty. Full prefill runs. This is the baseline.
Warm-1 (call 2): System prompt tokens should be in prefix cache from call 1. Saving is 
(
t
c
o
l
d
−
t
w
a
r
m
1
)
/
t
c
o
l
d
×
100
%
(t 
cold
​
 −t 
warm1
​
 )/t 
cold
​
 ×100%
Warm-2 (call 3): Same prefix still in cache. Should match or slightly improve warm-1.
The comparison that matters is Pipeline B (ON) warm reduction vs Pipeline A (OFF) warm reduction. If Pipeline A also shows warm reduction, that indicates the scheduler has inherent sequential-call optimization independent of explicit prefix caching.

Secondary metrics per call: combined_tps, acceptance_rate (speculative decode health), peak_rss_mb, tokens_output.

Calibration check: After Pipeline A completes, PA 4K cold TTFT is compared to the Task 4.4 reference (7,216ms). Acceptable range ±30%. If outside: flag CALIBRATION_WARNING but proceed — relative cold/warm deltas within Pipeline B are the primary result regardless.

5. PA Budget Gate and PREFIX_CACHE_MANDATORY_PA Trigger
From ADR-012 §2.5, the PA P95 budget is 2,000ms. The budget was derived from empirical baseline TTFT of \~300–408ms at 2K–4K context.

Gate G-04 (pa_budget_gate):

Condition	Flag	Consequence
Pipeline B, PA 4K, ttft_warm1 ≤ 300ms	PA_BUDGET_MET	Prefix cache is MANDATORY for PA — locked in ADR-012 §2.2
ttft_warm1 ≤ 1,500ms	PA_BUDGET_IMPROVED	Meaningful improvement; PA remains within 2,000ms budget with headroom
ttft_warm1 > 1,500ms	(value reported only)	Report actual; SDO evaluates against budget
Practical note: Given the Task 4.4 cold TTFT of 7,216ms at 4K (with max_new_tokens=128, AO-style), and the PA profile using max_new_tokens=32 with a shorter output path, the PA TTFT will differ. The 300ms warm target is likely from an earlier methodology and may not be achievable with the current pipeline. The task reports the actual measured value regardless.

6. Speculative Decoding Compatibility Risk and Response Protocol
Risk: OV GenAI 2026.0's prefix cache scheduler must coordinate KV state between the target Qwen3-14B and the draft Qwen3-0.6B. If this coordination is incomplete, prefix caching may be silently incompatible with speculative decoding.

Incompatibility indicators to watch for:

Pipeline B compilation fails with enable_prefix_caching=True → ABORT as SPEC_DECODE_INCOMPATIBLE
Pipeline B warm-1 TTFT ≥ Pipeline B cold TTFT at all bands and profiles → PREFIX_CACHE_NO_BENEFIT
AR drops to 0.000 in Pipeline B but not Pipeline A → SPEC_DECODE_INCOMPATIBLE (cache disabled spec-decode)
OOM or RuntimeError on first warm call → SPEC_DECODE_INCOMPATIBLE
OpenVINO logs a warning about incompatibility → SPEC_DECODE_INCOMPATIBLE
Response if SPEC_DECODE_INCOMPATIBLE: Save Pipeline A results as the final artifact, set spec_decode_compatibility: "SPEC_DECODE_INCOMPATIBLE" in the analysis section, lock prefix_cache=OFF for all production profiles in ADR-012 §2.2. Do not attempt workarounds.

If Pipeline B warm-1 TTFT > Pipeline B cold TTFT at all points (but no crash, no AR drop): flag CACHE_OVERHEAD — cache impose overhead with no benefit, possibly due to tiny prefix fraction.

7. Governance Updates Required on Completion
Update	Condition	Target
GOV-01: Update Pipeline kwargs row in ADR-012 §2.2	Always — replace EVALUATING with result-conditional locked/evaluating text based on disposition	ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md
GOV-02: Append new LEDGER entry	Always — next available entry number (currently Entry 19 is the last, Task 4.6 will be Entry 20)	POST_OPERATIONAL_MATURATION_LEDGER.md
Files changed (4 total): CREATE phase2_gates/scripts/run_p5_task4_6_prefix_cache.py, CREATE phase2_gates/evidence/p5_task4_6_prefix_cache_study.json, UPDATE ADR-012, UPDATE LEDGER.

No production code changes. services, shared, launcher, tests are untouched.

8. Pre-Condition Verification Checklist
Check	ID	Status	Evidence
Branch feature/p5-task4-6-prefix-cache exists	PC-01	✅ PASS	Branch present locally; was merged to main at a7b0c2b. Contains only SDO prompt commit db479c8. Task 4.4 evidence artifact present. Action required before coding: reset branch to current main HEAD or create fresh from main.
Task 4.4 reference TTFT values parsed	PC-02	✅ PASS	4K XAttn ON: TTFT=7,216ms, TPS=11.943. 12K XAttn ON: TTFT=42,390ms, TPS=6.091. Confirmed from p5_task4_4_xattention_sweep.json.
Target model paths exist	PC-03	✅ PASS	openvino_model.xml ✅ / .bin ✅
Draft-A model paths exist	PC-03	✅ PASS	openvino_model.xml ✅ / .bin ✅
SchedulerConfig.enable_prefix_caching attribute valid	PC-04	✅ PASS	attr_present: True, default: False. No PROPERTY_NOT_AVAILABLE abort needed.
AC power connected	PC-05	✅ PASS	power_plugged: True via psutil
.venv active with required packages	PC-06	✅ PASS	openvino_genai OK, psutil 7.2.2, transformers 4.51.3
Test suite baseline recorded	PC-07	✅ PASS	786 tests collected. Expected baseline: 755 passed / 31 deferred (p114 asyncio, pre-existing). Task 4.6 adds no unit tests.
All 7 PC checks pass. One action item before commencing code: the branch feature/p5-task4-6-prefix-cache needs to be reset to current main HEAD (a7b0c2b) since its only current commit is the SDO prompt document. I will checkout and reset the branch before writing any benchmark code.