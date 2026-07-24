---
title: P5_FEASIBILITY_005a_PROMPT
status: archived
area: portfolio
---

# P5-FEASIBILITY-005a Execution Prompt — Speculative Decoding & Draft Model Feasibility

Paste the XML block below into a new Execution Agent chat session along with the listed attachments.

---

## Required Attachments

1. `.github/copilot-instructions.md`
2. `shared/constants.py`
3. `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`
4. `docs/P5-MODEL-SELECTION-CROSS-REFERENCE.md`
5. `docs/FEASIBILITY_MULTI_DEVICE_CAPABILITY.md`  (P5-004 results)
6. `docs/FEASIBILITY_UNIFIED_MODEL.md`  (P5-005 INSUFFICIENT_EVIDENCE result)
7. `phase2_gates/scripts/acquire_p5_005_models.py`  (existing acquisition script — to be extended)
8. `phase2_gates/scripts/run_p5_feasibility_005.py`  (existing benchmark harness — to be extended)
9. `phase2_gates/evidence/p5_005_model_acquisition.json`  (P5-005 acquisition evidence showing failures)
10. `phase2_gates/evidence/p5_unified_model_feasibility_matrix.json`  (P5-005 blocked benchmark evidence)
11. `docs/adrs/ADR-006-Empirical-Memory-Budget-Tier-Summation.md`
12. `Use Cases_FINAL.md` (lines 253-380 — USE-CASE-005 specification)

---

## Context From P5-005 (Failed Run)

P5-005 was executed but disposition was `INSUFFICIENT_EVIDENCE`. All three model acquisitions
failed, which blocked the entire 10-test benchmark matrix.

**Failure chain:**
1. Initial blocker: `optimum-intel` import error (`cannot import name 'sdpa_mask_without_vmap'`).
   The execution agent patched this with a compatibility shim in `ensure_optimum_openvino_compatibility()`.
2. After the shim, Qwen3-14B conversion began but **OOM during CPU-side data-aware quantization**:
   `Failed to allocate 178421760 bytes of memory` at `FullyConnected node ...layers.28.mlp.gate_proj`.
   The FP16 14B model (\~30 GB) + calibration dataset + quantization working set exceeds the 32 GB
   system RAM.
3. The acquisition script may have subsequently attempted 8B and 0.6B — check process state.

**Existing model assets (already converted and validated from prior milestones):**
- `models/qwen3-1.7b/openvino-int4/` — 996 MB bin, `Qwen3ForCausalLM`, GPU-validated at 36 tps
- `models/qwen3-1.7b/openvino-int4-npu/` — 971 MB bin, NPU-targeted (validated in P5-004)
- `models/qwen2.5-1.5b-instruct/openvino-int4-npu/` — 976 MB bin (DO NOT use as draft — wrong family)

**Architecture Matching Constraint:**
All draft-target pairs MUST share the same model family. Qwen3 drafts for Qwen3 targets ONLY.
Mixing families (e.g., Qwen2.5 draft for Qwen3 target) will tank acceptance rates because their
learned token distributions, indentation patterns, and syntax generation diverge at the architectural
level — even though they share the same tokenizer vocabulary. This is especially destructive for
coding-specific generation where the target model's code patterns (indentation, syntax, bracket
placement) will routinely diverge from a different-family drafter's predictions.

---

## XML Execution Prompt

```xml
<execution_prompt milestone="P5-FEASIBILITY-005a" type="empirical_evidence_collection">

  <context>
    <summary>
      P5-FEASIBILITY-005 attempted to validate Qwen3-14B and Qwen3-8B as unified models
      on the Arc 140V GPU. The attempt FAILED at model acquisition phase — Qwen3-14B
      conversion OOM'd during data-aware INT4 quantization (FP16 model + calibration
      exceeds 32 GB system RAM), and the remaining models may or may not have completed.

      This follow-on study (P5-005a) resolves the acquisition blockers, expands the test
      matrix to include BOTH Qwen3-0.6B and Qwen3-1.7B as draft models for speculative
      decoding, and investigates NPU offloading of the draft model to keep the iGPU free
      for the target model.

      CRITICAL CONSTRAINT: All draft-target pairs MUST be from the same model family
      (Qwen3 only). Do NOT use Qwen2.5-1.5B as a draft model — it is a different
      architecture family and will have unacceptably low acceptance rates, especially for
      code generation patterns.
    </summary>

    <prior_evidence milestone="P5-005-BLOCKED">
      P5-005 disposition: INSUFFICIENT_EVIDENCE.
      Blocking condition: MODEL_ASSET_PRECHECK_FAILED.
      Acquisition errors:
        - qwen3-14b: OOM during CPU quantization (178MB alloc failed at layer 28)
        - qwen3-8b: Status unknown (acquisition script may still be running)
        - qwen3-0.6b: Status unknown (acquisition script may still be running)
      Evidence artifacts: p5_005_model_acquisition.json, p5_unified_model_feasibility_matrix.json
      Existing scripts: acquire_p5_005_models.py, run_p5_feasibility_005.py (both functional,
        need extension)
    </prior_evidence>

    <prior_evidence milestone="P5-004">
      Disposition: HYBRID_NPU_GPU.
      GPU proved 4-5x faster than NPU for generation:
        - GPU Qwen2.5-1.5B: 53 tps at 4096 user tokens
        - GPU Qwen3-1.7B: 36 tps at 4096 user tokens
        - NPU Qwen3-1.7B: ~3-14 tps (varies by MAX_PROMPT_LEN config)
        - CPU Qwen3-1.7B: 15 tps at 4096 user tokens
      Max measured RSS peak: 3,920 MB (well within budget).
    </prior_evidence>

    <hardware_inventory>
      <soc>Intel Core Ultra 7 258V (Lunar Lake)</soc>
      <gpu name="Arc 140V" arch="Xe2">
        8 Xe Cores, 128 XMX engines, 1950 MHz boost.
        ~136.5 GB/s theoretical bandwidth, ~62-73 GB/s effective.
      </gpu>
      <npu name="Intel AI Boost">
        Validated for Qwen3-1.7B in prior milestones.
        Already has converted model: models/qwen3-1.7b/openvino-int4-npu/
      </npu>
      <memory>32 GB LPDDR5X-8533 unified. Effective ceiling: 31,323 MB (ADR-005).
        Available for LLM agents: ~15,507 MB.</memory>
    </hardware_inventory>

    <model_inventory>
      <model name="qwen3-14b" hf_id="Qwen/Qwen3-14B" status="TO_BE_ACQUIRED">
        14.8B params, Qwen3ForCausalLM, vocab 151936.
        INT4 weights: ~7,700 MB. Total unified (3x 4K KV): ~10,020 MB.
        ACQUISITION BLOCKED IN P5-005: CPU OOM during data-aware quantization.
        See Phase 1 for resolution strategy.
      </model>

      <model name="qwen3-8b" hf_id="Qwen/Qwen3-8B" status="TO_BE_VERIFIED">
        8.2B params, Qwen3ForCausalLM, vocab 151936.
        INT4 weights: ~4,260 MB. Total unified: ~6,288 MB.
        May have been converted by the still-running P5-005 acquire process.
        Check models/qwen3-8b/openvino-int4-gpu/ for openvino_model.xml and .bin.
      </model>

      <model name="qwen3-0.6b" hf_id="Qwen/Qwen3-0.6B" status="TO_BE_VERIFIED" role="DRAFT">
        0.6B params, Qwen3ForCausalLM, vocab 151936. Dense.
        DRAFT model for standard assisted generation.
        GPU variant: ~400 MB INT4.
        NPU variant: TO_BE_CREATED (new in P5-005a).
        Check models/qwen3-0.6b/openvino-int4-gpu/ first.
      </model>

      <model name="qwen3-1.7b" status="AVAILABLE" role="DRAFT">
        1.7B params, Qwen3ForCausalLM, vocab 151936. Dense.
        DRAFT model — SAME FAMILY as targets. Architecture match CONFIRMED.
        GPU variant: models/qwen3-1.7b/openvino-int4/ (996 MB, VALIDATED at 36 tps GPU)
        NPU variant: models/qwen3-1.7b/openvino-int4-npu/ (971 MB, VALIDATED in P5-004)
        NO CONVERSION NEEDED — both variants already exist.
      </model>

      <model name="eagle3-candidates" status="TO_BE_INVESTIGATED" role="EAGLE3_DRAFT_HEAD">
        P5-005 EAGLE-3 candidate discovery found HuggingFace models matching both
        qwen3-8b and qwen3-14b naming patterns.
        If found and convertible: enables T-05 and T-07.
        If not found: those tests are SKIPPED (not a failure — EAGLE-3 is enhancement).
      </model>
    </model_inventory>

    <architecture_matching_rules>
      MANDATORY for all speculative/assisted generation tests:

      1. SAME FAMILY ONLY: Draft and target must share the same model architecture class.
         All Qwen3 models (0.6B, 1.7B, 8B, 14B) share Qwen3ForCausalLM — VALID pairs.
         Qwen2.5-1.5B uses a different architecture — INVALID as draft for Qwen3 targets.

      2. SAME TOKENIZER: Draft and target must use identical tokenizer. All Qwen3 models
         share vocab_size=151936 with identical BPE merges — VALID.

      3. CODE GENERATION AWARENESS: When the target model generates code (indentation,
         syntax, bracket-matching), a smaller same-family draft model will still have
         reasonable acceptance rates because it learned from the SAME training distribution.
         A cross-family draft (e.g., Qwen2.5 drafting for Qwen3) would have divergent
         code generation patterns, tanking acceptance rates. This is why family matching
         is mandatory.

      4. THINKING MODE CONSIDERATION: Qwen3 models support /think and /no_think modes.
         Draft model acceptance rates may differ between thinking (chain-of-thought) and
         non-thinking (direct response) generation patterns. Measure both if time permits.

      5. SIZE RATIO SWEET SPOT: For speculative decoding, the draft-target size ratio
         affects the tradeoff between draft speed and acceptance rate:
         - 0.6B → 14B (24:1 ratio) — very fast drafts, potentially lower acceptance
         - 1.7B → 14B (8.7:1 ratio) — slower drafts, potentially higher acceptance
         - 0.6B → 8B (13.7:1 ratio) — moderate ratio
         - 1.7B → 8B (4.7:1 ratio) — may be too close (draft overhead dominates)
         The benchmark must measure all four to find the empirical sweet spot.
    </architecture_matching_rules>

    <openvino_environment>
      <install_location>C:\Users\mrbla\BlarAI\.venv</install_location>
      <python>C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe (Python 3.11.9)</python>
      <openvino_version>2026.0.0-20965-c6d6a13a886-releases/2026/0</openvino_version>
      <genai_version>2026.0.0.0-2820-dab5b993a38</genai_version>
      <note>
        Run ALL scripts with the .venv Python. Do NOT use any other venv.
        optimum-intel and nncf are installed (nncf was upgraded to >=2.19.0 during P5-005).
        The ensure_optimum_openvino_compatibility() shim in acquire_p5_005_models.py
        patches the sdpa_mask_without_vmap import error.
      </note>
    </openvino_environment>

    <constraints>
      <memory_ceiling>31,323 MB effective (ADR-005). Available for LLM agents: ~15,507 MB.</memory_ceiling>
      <memory_warning>When testing 14B + draft model combos, monitor total RSS carefully.
        14B weights (~7.7 GB) + 1.7B draft (~1 GB) + KV caches + runtime could approach
        ~12 GB. Set RSS warning at 26,000 MB.</memory_warning>
      <privacy>No external network calls during BENCHMARKING. HuggingFace download authorized
        during acquisition phase ONLY.</privacy>
      <power>Must run on AC power. Detect and enforce via psutil before benchmarking.</power>
      <security>Fail-closed on all errors. No partial results treated as success.</security>
      <disk_space>Check with psutil.disk_usage('C:\\'). Require >=20 GB free.</disk_space>
    </constraints>
  </context>

  <objective>
    Produce a comprehensive Unified Model + Draft Model Feasibility Matrix that:

    1. RESOLVES the P5-005 model acquisition blockers (especially 14B OOM).
    2. EMPIRICALLY benchmarks Qwen3-14B and Qwen3-8B with the base optimization features
       (baseline, INT8 KV, XAttention, prefix caching, EAGLE-3 where available).
    3. COMPARES two draft model sizes (Qwen3-0.6B vs Qwen3-1.7B) for speculative decoding
       with BOTH target models on GPU.
    4. INVESTIGATES NPU offloading of the draft model — running the draft on NPU while
       the target model remains on GPU, freeing GPU compute/memory for the target.
    5. ENFORCES architecture matching (Qwen3 family only for all draft-target pairs).

    Primary question: Can Qwen3-14B deliver >=8 tok/s on GPU, and which draft model
    configuration (size + device) maximizes throughput?

    Secondary: Which draft model size (0.6B vs 1.7B) achieves better effective speedup?

    Tertiary: Can the draft model be offloaded to NPU to free GPU resources, and does the
    cross-device overhead negate the speculative decoding benefit?
  </objective>

  <execution_plan>

    <phase number="0" name="Process Cleanup and State Assessment">
      <description>
        P5-005's acquisition script may still be running. Assess the current state
        before taking any action.
      </description>
      <step>Check for running Python processes that might be the P5-005 acquire script:
            Get-Process -Name python* | Select-Object Id, ProcessName, WorkingSet, StartTime
            Look for a process running acquire_p5_005_models.py (started around 20:39 on 2026-02-26).</step>
      <step>If the acquisition process is still running:
            - Check if it has produced any new model files since P5-005's evidence was written.
            - Check models/qwen3-8b/openvino-int4-gpu/ and models/qwen3-0.6b/openvino-int4-gpu/
              for openvino_model.xml and openvino_model.bin.
            - If it appears stuck or non-productive (same working set for >5 minutes,
              no new files being written), terminate it: Stop-Process -Id [PID] -Force
            - If it is actively converting a model (growing disk usage), let it complete.</step>
      <step>Read the current p5_005_model_acquisition.json to see which models succeeded/failed.
            Record the exact state in the new evidence artifact.</step>
      <step>Verify existing model assets:
            - models/qwen3-1.7b/openvino-int4/ — must have openvino_model.xml + .bin (~996 MB)
            - models/qwen3-1.7b/openvino-int4-npu/ — must have openvino_model.xml + .bin (~971 MB)
            - models/qwen3-14b/openvino-int4-gpu/ — check if populated since failure
            - models/qwen3-8b/openvino-int4-gpu/ — check if populated
            - models/qwen3-0.6b/openvino-int4-gpu/ — check if populated</step>
    </phase>

    <phase number="1" name="Model Acquisition — Resolve Blockers">
      <description>
        Acquire all models needed for the expanded test matrix. The key blocker from P5-005
        is that Qwen3-14B data-aware INT4 quantization OOM'd on CPU (32 GB system RAM is
        insufficient for loading ~30 GB FP16 weights + calibration). Apply alternative
        strategies in priority order.
      </description>

      <step name="14B Acquisition — Alternative Strategy">
        The standard optimum-intel export with scale_estimation=True and dataset=wikitext2
        requires too much RAM for 14B. Try these alternatives IN ORDER. Stop at first success:

        STRATEGY A — Search for pre-quantized OpenVINO INT4 models on HuggingFace:
          Use huggingface_hub.HfApi().list_models(search="Qwen3-14B openvino int4")
          and similar queries. Look for community-quantized INT4 models that include
          openvino_model.xml and openvino_model.bin. If found:
            - Download with huggingface_hub.snapshot_download()
            - Verify files exist and bin size is 6,500-9,000 MB
            - Run quick inference smoke test with LLMPipeline("...", "GPU")
            - If smoke test passes, this model is ACCEPTED.

        STRATEGY B — Use optimum-cli with reduced calibration:
          optimum-cli export openvino --model Qwen/Qwen3-14B --weight-format int4 \
            --group-size 128 --ratio 1.0 --sym false \
            --num-calibration-samples 32 \
            models/qwen3-14b/openvino-int4-gpu
          The --num-calibration-samples 32 (down from default ~128) reduces peak RAM.
          Note: This uses the command-line tool instead of the Python API, which has
          lower overhead.

        STRATEGY C — Drop data-aware quantization (fastest, least accurate):
          Use the Python API but WITHOUT scale_estimation and dataset:
          quantization_config = {"bits": 4, "sym": False, "group_size": 128, "ratio": 1.0}
          (no scale_estimation, no dataset)
          This performs basic weight-only quantization without calibration data,
          using much less RAM.

        STRATEGY D — If all above fail, mark Qwen3-14B as ACQUISITION_FAILED and proceed
          with Qwen3-8B only. This is a valid outcome — the study continues with 8B.

        Record which strategy succeeded in the evidence artifact.
      </step>

      <step name="8B Acquisition">
        Check if models/qwen3-8b/openvino-int4-gpu/ already has valid model files from
        the still-running P5-005 acquire process.

        If NOT present:
          - Try the standard optimum-intel export first (8B FP16 is ~16 GB, should fit in
            32 GB RAM with calibration).
          - If OOM: apply same Strategy A/B/C cascade as 14B.
          - Validate: bin size 3,500-5,500 MB, quick inference smoke test on GPU.
      </step>

      <step name="0.6B Acquisition — GPU variant">
        Check if models/qwen3-0.6b/openvino-int4-gpu/ already has valid model files.
        If NOT present:
          - Standard optimum-intel export (0.6B is tiny, no RAM issues).
          - quantization_config: bits=4, sym=False, group_size=128, ratio=1.0
          - Validate: bin size 300-600 MB, quick inference smoke test on GPU.
      </step>

      <step name="0.6B Acquisition — NPU variant (NEW)">
        Convert Qwen3-0.6B for NPU deployment.
        Output path: models/qwen3-0.6b/openvino-int4-npu/

        Use the same optimum-intel export as the GPU variant. The OpenVINO IR format
        is device-agnostic, but NPU compilation may require specific pipeline config.

        Approach: Copy the GPU variant model files, then test if LLMPipeline can load
        them with device="NPU". If NPU compilation succeeds, the model is NPU-ready.
        If NPU requires specific MAX_PROMPT_LEN config, apply it.

        Alternative: If the GPU-exported model doesn't compile on NPU, try exporting
        specifically with NPU-targeted config (reference: how qwen3-1.7b/openvino-int4-npu
        was originally created — check its openvino_config.json for clues).

        Validation: Load with LLMPipeline("...", "NPU"), generate 10 tokens. If it works,
        record as NPU-validated.
      </step>

      <step name="1.7B — Verify Existing Assets">
        The 1.7B model in BOTH GPU and NPU variants already exists:
        - models/qwen3-1.7b/openvino-int4/ — verify openvino_model.xml + .bin intact
        - models/qwen3-1.7b/openvino-int4-npu/ — verify openvino_model.xml + .bin intact
        NO CONVERSION NEEDED. Just validate presence and file integrity.
      </step>

      <step name="EAGLE-3 Investigation">
        Same as P5-005: query HuggingFace for EAGLE-3 draft heads for Qwen3-8B and Qwen3-14B.
        If found and downloadable, convert to OpenVINO IR. If not found, mark EAGLE-3 tests
        as SKIPPED (not a failure).
      </step>

      <step name="Acquisition Evidence">
        Write comprehensive acquisition evidence to:
        phase2_gates/evidence/p5_005a_model_acquisition.json

        Include for each model: strategy used, status, elapsed time, bin size, SHA-256,
        smoke test result, device target (GPU/NPU).
      </step>
    </phase>

    <phase number="2" name="Cross-Device Draft Model API Discovery">
      <description>
        A critical unknown: does OpenVINO GenAI's draft_model() API support CROSS-DEVICE
        operation — i.e., draft model on NPU while target model on GPU?

        The API signature is: ov_genai.draft_model(model_path, device_string)
        The LLMPipeline is: ov_genai.LLMPipeline(model_path, "GPU", config)

        Question: Can we pass device_string="NPU" to draft_model while the pipeline
        runs on "GPU"? This would enable keeping the iGPU free for the target model
        while the draft model runs on the NPU.
      </description>

      <step>Create a minimal test script phase2_gates/scripts/test_cross_device_draft.py:
        1. Load qwen3-1.7b/openvino-int4/ as target on "GPU"
        2. Load qwen3-1.7b/openvino-int4-npu/ as draft on "NPU" via:
           config["draft_model"] = ov_genai.draft_model("models/qwen3-1.7b/openvino-int4-npu", "NPU")
           pipe = ov_genai.LLMPipeline("models/qwen3-1.7b/openvino-int4", "GPU", config)
        3. Attempt a short generation (10 tokens).
        4. Record success/failure and any error messages.
        5. If cross-device FAILS, try:
           a. Loading draft on "CPU" instead (CPU offload is also a valid strategy to free GPU)
           b. Record which device combinations work and which don't
      </step>

      <step>Capture discovery results in:
        phase2_gates/evidence/p5_005a_cross_device_draft_discovery.json

        Fields: {
          "draft_on_npu_target_on_gpu": {"supported": bool, "error": str|null},
          "draft_on_cpu_target_on_gpu": {"supported": bool, "error": str|null},
          "draft_on_gpu_target_on_gpu": {"supported": bool, "error": str|null}
        }
      </step>

      <step>This discovery GATES the NPU-offloaded draft tests (T-13 through T-16).
        If cross-device is not supported, those tests are SKIPPED with disposition
        CROSS_DEVICE_DRAFT_NOT_SUPPORTED. This is a valid finding, not a failure.</step>
    </phase>

    <phase number="3" name="Benchmark Script Extension">
      <description>
        Extend run_p5_feasibility_005.py (or create run_p5_feasibility_005a.py) with
        the expanded test matrix. The existing harness infrastructure (RssSampler,
        run_single_generation, stats, summarize_runs, etc.) is reused as-is.
      </description>

      <test_matrix>
        === BASE TESTS (from P5-005, unchanged) ===

        T-01: 14B Baseline (GPU only, no optimizations)
        T-02: 14B + INT8 KV-cache (GPU, KV_CACHE_PRECISION=u8)
        T-03: 14B + INT8 KV + XAttention (GPU, +GPU_ENABLE_SDPA_OPTIMIZATION)
        T-04: 14B Full Optimization Stack (INT8 KV + XAttention + prefix caching)
        T-05: 14B + EAGLE-3 draft head (GPU, if available — SKIP if not)
        T-06: 8B Baseline (GPU only)
        T-07: 8B + EAGLE-3 draft head (GPU, if available — SKIP if not)
        T-08: 8B Full Optimization Stack

        === SPECULATIVE DECODING — GPU DRAFT (existing T-09/T-10 expanded) ===

        T-09:  14B target (GPU) + Qwen3-0.6B draft (GPU)  — standard assisted generation
        T-10:  8B target (GPU) + Qwen3-0.6B draft (GPU)   — standard assisted generation
        T-11:  14B target (GPU) + Qwen3-1.7B draft (GPU)  — standard assisted generation [NEW]
        T-12:  8B target (GPU) + Qwen3-1.7B draft (GPU)   — standard assisted generation [NEW]

        === SPECULATIVE DECODING — NPU-OFFLOADED DRAFT (all NEW) ===
        (Only execute if Phase 2 cross-device discovery confirms NPU draft is supported)

        T-13:  14B target (GPU) + Qwen3-0.6B draft (NPU)  — cross-device assisted gen
        T-14:  14B target (GPU) + Qwen3-1.7B draft (NPU)  — cross-device assisted gen
        T-15:  8B target (GPU) + Qwen3-0.6B draft (NPU)   — cross-device assisted gen
        T-16:  8B target (GPU) + Qwen3-1.7B draft (NPU)   — cross-device assisted gen

        === CPU-OFFLOADED DRAFT FALLBACK (contingency — only if NPU draft fails) ===
        (Only execute if NPU cross-device failed AND CPU cross-device worked in Phase 2)

        T-17:  14B target (GPU) + Qwen3-1.7B draft (CPU)  — CPU-offloaded assisted gen
        T-18:  8B target (GPU) + Qwen3-1.7B draft (CPU)   — CPU-offloaded assisted gen
      </test_matrix>

      <test_execution_details>
        Prompt bands: [128, 256, 512, 1024, 2048, 3072, 4096]
        Warmup runs per band: 2 (discarded)
        Measured runs per band: 5
        Max new tokens per generation: 128
        Temperature: 0.0 (deterministic)

        For each test, capture:
        - TTFT (time to first token)
        - Total latency
        - Decode tokens/sec
        - RSS peak (via RssSampler)
        - Tokens generated
        - Error fingerprints (if any)

        For speculative decoding tests (T-09 through T-18), additionally compute:
        - SPEEDUP FACTOR = (test TPS mean at band 512) / (baseline TPS mean at band 512)
          where baseline = T-01 for 14B-target tests, T-06 for 8B-target tests
        - This is the proxy metric for acceptance rate — higher speedup = better matching.

        GenerationConfig for assisted generation tests:
          config.num_assistant_tokens = 5
          config.assistant_confidence_threshold = 0.35

        Pipeline creation for GPU-only draft:
          config["draft_model"] = ov_genai.draft_model(str(draft_path), "GPU")
          pipe = ov_genai.LLMPipeline(str(target_path), "GPU", config)

        Pipeline creation for NPU-offloaded draft:
          config["draft_model"] = ov_genai.draft_model(str(draft_npu_path), "NPU")
          pipe = ov_genai.LLMPipeline(str(target_path), "GPU", config)

        Pipeline creation for CPU-offloaded draft:
          config["draft_model"] = ov_genai.draft_model(str(draft_path), "CPU")
          pipe = ov_genai.LLMPipeline(str(target_path), "GPU", config)

        Memory cleanup between tests: del pipe; gc.collect(); time.sleep(2)
      </test_execution_details>

      <model_paths>
        TARGET models:
          MODEL_14B = models/qwen3-14b/openvino-int4-gpu/
          MODEL_8B  = models/qwen3-8b/openvino-int4-gpu/

        DRAFT models (GPU variants):
          DRAFT_06B_GPU = models/qwen3-0.6b/openvino-int4-gpu/
          DRAFT_17B_GPU = models/qwen3-1.7b/openvino-int4/

        DRAFT models (NPU variants):
          DRAFT_06B_NPU = models/qwen3-0.6b/openvino-int4-npu/
          DRAFT_17B_NPU = models/qwen3-1.7b/openvino-int4-npu/

        EAGLE-3 models (if available):
          EAGLE3_14B = models/eagle3-qwen3-14b/
          EAGLE3_8B  = models/eagle3-qwen3-8b/
      </model_paths>

      <skip_logic>
        A test is SKIPPED (not failed) if:
        - Its target model was not acquired (acquisition failure)
        - Its draft model was not acquired or not available for the required device
        - EAGLE-3 draft heads not found (T-05, T-07)
        - Cross-device draft not supported by API (T-13 through T-18)
        - A test's dependency test failed catastrophically (e.g., T-01 pipeline creation
          failed → skip all 14B tests)

        Record skip reason in the evidence artifact.
      </skip_logic>
    </phase>

    <phase number="4" name="Run Benchmark Matrix">
      <step>Verify AC power (fail-closed if on battery)</step>
      <step>Run tests in order: T-01 through T-18 (skipping as appropriate)</step>
      <step>Write progressive results to:
            phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json
            (atomic write after each test completes)</step>
      <step>Estimated runtime: 90-180 minutes depending on how many tests execute.
            The 14B tests at higher prompt bands will be the slowest.</step>
      <step>If T-01 pipeline creation fails (14B cannot load on GPU at all), immediately
            fall through to T-06 (8B baseline). Do not skip 8B tests because of 14B failure.</step>
    </phase>

    <phase number="5" name="Analysis and Report">
      <description>
        Produce the final analysis document and quality gate evaluation.
      </description>

      <step>Create or update: docs/FEASIBILITY_UNIFIED_MODEL.md
        Replace the INSUFFICIENT_EVIDENCE content with actual results.

        Required sections:
        1) Model Acquisition Results (which strategies succeeded, failure details)
        2) Cross-Device Draft Discovery Results (NPU/CPU/GPU draft support)
        3) Qwen3-14B Base Results (T-01 through T-04)
        4) Qwen3-8B Base Results (T-06, T-08)
        5) EAGLE-3 Results (T-05, T-07 — or SKIPPED disposition)
        6) Speculative Decoding Comparison — THE KEY SECTION:

           Create a comparison table:

           | Test | Target | Draft Model | Draft Device | TPS@512 | Speedup vs Baseline | Memory Peak |
           |------|--------|-------------|--------------|---------|---------------------|-------------|
           | T-09 | 14B    | 0.6B        | GPU          | ...     | ...x                | ... MB      |
           | T-11 | 14B    | 1.7B        | GPU          | ...     | ...x                | ... MB      |
           | T-13 | 14B    | 0.6B        | NPU          | ...     | ...x                | ... MB      |
           | T-14 | 14B    | 1.7B        | NPU          | ...     | ...x                | ... MB      |
           | T-10 | 8B     | 0.6B        | GPU          | ...     | ...x                | ... MB      |
           | T-12 | 8B     | 1.7B        | GPU          | ...     | ...x                | ... MB      |
           | T-15 | 8B     | 0.6B        | NPU          | ...     | ...x                | ... MB      |
           | T-16 | 8B     | 1.7B        | NPU          | ...     | ...x                | ... MB      |
           | T-17 | 14B    | 1.7B        | CPU          | ...     | ...x                | ... MB      |
           | T-18 | 8B     | 1.7B        | CPU          | ...     | ...x                | ... MB      |

        7) Draft Model Size Analysis:
           - For each target size (14B, 8B), compare 0.6B vs 1.7B draft speedup
           - Identify which draft size achieves better effective throughput
           - Note the tradeoff: 1.7B is slower per-draft-token but potentially higher
             acceptance rate (more tokens accepted per verification cycle)

        8) NPU Offload Analysis:
           - Compare GPU-draft vs NPU-draft speedup for the same draft size
           - Quantify cross-device overhead (NPU→GPU token transfer latency)
           - Determine whether NPU offload is NET POSITIVE (frees GPU) or NET NEGATIVE
             (cross-device overhead negates speculative benefit)

        9) Production Configuration Recommendation:
           - Best target model (14B or 8B)
           - Best draft model (0.6B or 1.7B)
           - Best draft device (GPU, NPU, or CPU)
           - Best optimization stack (INT8 KV, XAttention, prefix caching)
           - Composite recommendation

        10) Disposition (see quality gate)
      </step>
    </phase>

    <phase number="6" name="Commit and Ledger Update">
      <step>Stage changed/new files:
        - phase2_gates/scripts/acquire_p5_005_models.py (if modified)
        - phase2_gates/scripts/run_p5_feasibility_005a.py (or modified 005.py)
        - phase2_gates/scripts/test_cross_device_draft.py
        - phase2_gates/evidence/p5_005a_model_acquisition.json
        - phase2_gates/evidence/p5_005a_cross_device_draft_discovery.json
        - phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json
        - docs/FEASIBILITY_UNIFIED_MODEL.md (updated)
        - docs/POST_OPERATIONAL_MATURATION_LEDGER.md (new entry appended)
      </step>
      <step>Commit with message:
        P5-FEASIBILITY-005a: unified model + draft model feasibility matrix [DISPOSITION]

        Replace [DISPOSITION] with the actual quality gate disposition.</step>
      <step>Append entry to docs/POST_OPERATIONAL_MATURATION_LEDGER.md following the format
        of existing entries. Include: milestone type, primary artifact, evidence index,
        scope completed, key findings, quality gate result, disposition, notes.</step>
    </phase>
  </execution_plan>

  <quality_gate name="Unified Model + Draft Feasibility Gate (UMDFG)">
    <gate id="G-01" required="true">
      At least one configuration (any test) achieves >=8 tps mean decode at band 512.
    </gate>
    <gate id="G-02" required="false" type="enhancement">
      At least one speculative decoding configuration achieves >=1.3x speedup over its
      baseline at band 512.
    </gate>
    <gate id="G-03" required="true">
      The recommended configuration's peak RSS stays within 15,507 MB memory budget.
    </gate>
    <gate id="G-04" required="true">
      The recommended configuration has >=4 valid runs out of 5 measured runs for ALL
      7 prompt bands.
    </gate>
    <gate id="G-05" required="false" type="draft_comparison">
      Draft model comparison captured: both 0.6B and 1.7B tested with at least one target.
    </gate>
    <gate id="G-06" required="false" type="npu_offload">
      NPU draft offload discovery completed (even if result is "not supported").
    </gate>
    <gate id="G-07" required="true">
      At least 3 distinct test configurations completed with valid data at band 512
      (sufficient for cross-comparison).
    </gate>

    <dispositions>
      QWEN3_14B_WITH_SPEC_DECODING — 14B meets threshold and speculative decoding improves it >=1.3x
      QWEN3_14B_CONFIRMED — 14B meets threshold without speculative decoding
      QWEN3_14B_MARGINAL — 14B achieves 6-8 tps (below threshold but close)
      QWEN3_8B_WITH_SPEC_DECODING — 8B + speculative decoding achieves good throughput
      QWEN3_8B_FALLBACK — 8B meets threshold, 14B does not
      BOTH_INFEASIBLE — Neither model meets threshold on this hardware
      INSUFFICIENT_EVIDENCE — Not enough valid data to make a determination
    </dispositions>
  </quality_gate>

  <rules>
    <rule id="R-01">Use .venv Python for ALL script execution. Command:
      .\.venv\Scripts\python.exe script.py</rule>
    <rule id="R-02">Every evidence JSON must include timestamp, git hash, platform, OV version.</rule>
    <rule id="R-03">Fail-closed: any uncaught exception produces a deterministic fingerprint
      and the test is marked failed, not silently dropped.</rule>
    <rule id="R-04">Memory safety: if any run exceeds 26,000 MB RSS, abort that test
      immediately and record the peak before cleanup.</rule>
    <rule id="R-05">AC power enforcement before and during benchmark phases.</rule>
    <rule id="R-06">Atomic JSON writes (write .tmp then rename) to prevent corruption.</rule>
    <rule id="R-07">No modifications to services/, shared/, or launcher/ — this is
      feasibility-only, not production code changes.</rule>
    <rule id="R-08">No external network calls during benchmark phases. HuggingFace
      access ONLY during Phase 1 acquisition.</rule>
    <rule id="R-09">Draft model architecture matching: ALL draft-target pairs MUST use
      Qwen3 family models. Do NOT use Qwen2.5-1.5B as a draft model.</rule>
    <rule id="R-10">If 14B acquisition fails entirely (all strategies), proceed with 8B-only
      test matrix. The study is still valid with 8B results.</rule>
    <rule id="R-11">EAGLE-3 draft heads are enhancement-only. If not found on HuggingFace,
      T-05 and T-07 are SKIPPED with appropriate disposition.</rule>
    <rule id="R-12">NPU cross-device draft is investigational. If the API does not support
      cross-device draft_model, T-13 through T-18 are SKIPPED. This is a FINDING, not a failure.</rule>
    <rule id="R-13">Between each test configuration, delete the pipeline, call gc.collect(),
      and sleep(2) to ensure clean memory state.</rule>
    <rule id="R-14">Record the precise model paths used for each test in the evidence artifact
      so results are reproducible.</rule>
    <rule id="R-15">The 1.7B GPU model path is models/qwen3-1.7b/openvino-int4/ (NOT
      openvino-int4-gpu — this model was converted in an earlier milestone with a different
      naming convention). Do not rename it.</rule>
    <rule id="R-16">Stop after milestone completion — do not start unrequested work.</rule>
    <rule id="R-17">Reuse existing harness infrastructure (RssSampler, run_single_generation,
      stats, summarize_runs, make_generation_config, etc.) from run_p5_feasibility_005.py.
      Extend, do not rewrite from scratch.</rule>
  </rules>

</execution_prompt>
```
