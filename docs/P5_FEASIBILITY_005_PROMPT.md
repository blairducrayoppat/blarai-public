# P5-FEASIBILITY-005 Execution Prompt

Paste the XML block below into a new Execution Agent chat session along with the listed attachments.

---

## Required Attachments

1. `.github/copilot-instructions.md`
2. `shared/constants.py`
3. `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`
4. `docs/P5-MODEL-SELECTION-CROSS-REFERENCE.md`
5. `docs/FEASIBILITY_MULTI_DEVICE_CAPABILITY.md`
6. `phase2_gates/scripts/run_p5_feasibility_004.py` (full file — benchmark infrastructure reference)
7. `phase2_gates/scripts/acquire_models.py` (full file — model acquisition pattern reference)
8. `phase2_gates/evidence/p5_multi_device_capability_matrix.json` (first 200 lines — P5-004 evidence format)
9. `docs/adrs/ADR-006-Empirical-Memory-Budget-Tier-Summation.md`
10. `Use Cases_FINAL.md` (lines 253-380 — USE-CASE-005 specification)

---

## Key Discovery (from P5-004 and SDO Model Selection Analysis)

P5-FEASIBILITY-004 proved GPU generation is **4-5× faster** than NPU (53 tps vs 3-14 tps for
Qwen2.5-1.5B at overlapping prompt lengths). The SDO subsequently conducted a comprehensive
model selection cross-reference across 8 candidates. Key conclusions:

1. **Qwen3-30B-A3B (MoE) ELIMINATED** — 16,100 MB weights exceed 15,507 MB budget.
2. **Qwen3-14B selected as PRIMARY** unified model (PA + AO + Code Agent via mmap weight sharing).
   Extrapolated 8-9.5 tps decode on Arc 140V. 10,020 MB total, 35% headroom.
3. **Qwen3-8B selected as FALLBACK** — 14-17 tps extrapolated, 59% headroom, EAGLE-3 validated in OV 2026.0.
4. **Unified > Separate** — dual-angle analysis proved unified model architecture superior.
5. **All throughput is EXTRAPOLATED** from 7B benchmarks. Empirical validation is the purpose of this milestone.

**OpenVINO 2026.0 features to validate empirically:**
- **EAGLE-3 speculative decoding** — validated for Qwen3-8B, NOT validated for Qwen3-14B
- **INT8 KV-cache** — reduces KV memory by 2× vs FP16 (160 KB → 80 KB per token for 14B)
- **XAttention (Block Sparse Attention)** — Xe2 preview, improves TTFT
- **Prefix caching** — eliminates redundant prefill for repeated system prompts
- **Standard assisted generation** — Qwen3-0.6B as standalone draft model (non-EAGLE-3 path)

---

## XML Execution Prompt

```xml
<execution_prompt milestone="P5-FEASIBILITY-005" type="empirical_evidence_collection">

  <context>
    <summary>
      P5-FEASIBILITY-004 established that GPU is the superior generation device on this
      hardware (4-5× faster than NPU). A comprehensive model selection analysis narrowed
      the field to Qwen3-14B (PRIMARY) and Qwen3-8B (FALLBACK) as unified models serving
      all three agent roles (PA, AO, Code Agent) via zero-copy mmap weight sharing.

      ALL throughput estimates for these models are EXTRAPOLATED from smaller 7B benchmarks.
      This milestone empirically measures actual decode throughput, TTFT, and memory for
      Qwen3-14B and Qwen3-8B on the Arc 140V GPU with multiple OpenVINO 2026.0 optimization
      features (INT8 KV-cache, XAttention, prefix caching, EAGLE-3 speculative decoding,
      and standard assisted generation with Qwen3-0.6B as draft model).

      The 10-test matrix below determines:
      1. Does Qwen3-14B meet the ≥8 tps threshold empirically?
      2. Which optimization features deliver measurable improvement?
      3. Does EAGLE-3 work with Qwen3-14B (unvalidated by Intel)?
      4. Is standard assisted generation (Qwen3-0.6B draft) a viable alternative to EAGLE-3?
      5. What is the optimal configuration for production deployment?
      6. If 14B fails thresholds, does Qwen3-8B meet them as fallback?
    </summary>

    <prior_evidence>
      <study id="P5-001" disposition="DO-NOT-EXPAND" type="analytical">
        Analytical context window study. Concluded DO-NOT-EXPAND for token limits.
        Not directly relevant to this milestone except as background.
      </study>
      <study id="P5-002" disposition="NO_DECISION" type="empirical">
        NPU-only latency measurement. Blocked by MAX_PROMPT_LEN software default.
        Evidence: p5_input_length_latency_matrix.json, p5_output_length_latency_matrix.json.
      </study>
      <study id="P5-003" disposition="NO_DECISION" type="empirical">
        NPU runtime ceiling characterization. Confirmed fail-closed containment.
        Evidence: p5_runtime_ceiling_characterization.json.
      </study>
      <study id="P5-004" disposition="HYBRID_NPU_GPU" type="empirical">
        Multi-device capability matrix. KEY FINDINGS FOR THIS MILESTONE:
        - GPU Qwen2.5-1.5B: 53 tps at 4096 tokens (the reference point)
        - GPU Qwen3-1.7B: 36 tps at 4096 tokens
        - GPU is 4-5× faster than NPU at overlapping prompt lengths
        - Peak RSS: 3,920 MB (well below 28 GB warning)
        - All DCG gates (DCG-01 through DCG-07) PASSED
        Evidence: p5_multi_device_capability_matrix.json.
      </study>
      <study id="SDO-CROSS-REF" type="analytical">
        Model selection cross-reference. 8 candidates evaluated. Key data:
        - Qwen3-14B INT4 weights: ~7,700 MB. Total unified (3× 4K KV): ~10,020 MB.
        - Qwen3-8B INT4 weights: ~4,260 MB. Total unified: ~6,288 MB.
        - Extrapolated 14B throughput: 8.0-9.5 tps (bandwidth-bound from 7B data).
        - Extrapolated 8B throughput: 14-17 tps.
        - KV-cache per token: 14B = 160 KB (FP16), 8B = 144 KB (FP16).
        - INT8 KV halves these: 14B = 80 KB, 8B = 72 KB per token.
        Artifact: docs/P5-MODEL-SELECTION-CROSS-REFERENCE.md.
      </study>
    </prior_evidence>

    <hardware_inventory>
      <device name="GPU" chip="Intel Arc 140V (Xe2 Battlemage, 8 Xe Cores, 128 XMX, 1950 MHz)">
        PRIMARY inference device for this milestone.
        Memory bandwidth: ~136.5 GB/s theoretical, ~62-73 GB/s effective (measured from 7B benchmarks).
        XAttention: Block Sparse Attention preview available on Xe2/Xe3.
        Dynamic quantization enabled by default on XMX hardware since OV 2025.2.
      </device>
      <device name="CPU" chip="Intel Core Ultra 7 258V (4P+4E cores, 8 threads)">
        NOT the focus of this milestone. Available as fallback reference only.
      </device>
    </hardware_inventory>

    <model_inventory>
      <model name="qwen3-14b" hf_id="Qwen/Qwen3-14B" status="TO_BE_ACQUIRED">
        14.8B params, dense, 40 layers, 40 Q-heads / 8 KV-heads (GQA), head_dim=128.
        Thinking/non-thinking dual mode. Native agentic/tool-calling (BFCL-validated).
        32K native context, 131K with YaRN. Apache-2.0 license.
        Target quantization: INT4_ASYM, group_size=128, ratio=1.0, scale_estimation=True.
        Target output path: models/qwen3-14b/openvino-int4-gpu/
        Estimated INT4 weight file: ~7,700 MB.
      </model>
      <model name="qwen3-8b" hf_id="Qwen/Qwen3-8B" status="TO_BE_ACQUIRED">
        8.2B params, dense, 36 layers, 32 Q-heads / 8 KV-heads (GQA), head_dim=128.
        Same dual-mode + agentic capabilities as 14B. Apache-2.0.
        Target quantization: INT4_ASYM, group_size=128, ratio=1.0, scale_estimation=True.
        Target output path: models/qwen3-8b/openvino-int4-gpu/
        Estimated INT4 weight file: ~4,260 MB.
      </model>
      <model name="qwen3-0.6b" hf_id="Qwen/Qwen3-0.6B" status="TO_BE_ACQUIRED">
        0.6B params, dense. Used as DRAFT model for standard assisted generation (T-09, T-10).
        Target quantization: INT4_ASYM, group_size=128, ratio=1.0 (simpler — small model).
        Target output path: models/qwen3-0.6b/openvino-int4-gpu/
        Estimated INT4 weight file: ~400 MB.
      </model>
      <model name="eagle3-qwen3-8b-draft" status="TO_BE_INVESTIGATED">
        EAGLE-3 draft head for Qwen3-8B. Intel validated this in OV 2026.0. Source TBD —
        search HuggingFace for "eagle3" + "qwen3" or check OpenVINO model zoo / notebooks.
        If found: convert to OpenVINO IR format for use with LLMPipeline speculative decoding.
        If NOT found: T-07 is SKIPPED with disposition EAGLE3_DRAFT_NOT_AVAILABLE.
      </model>
      <model name="eagle3-qwen3-14b-draft" status="TO_BE_INVESTIGATED">
        EAGLE-3 draft head for Qwen3-14B. NOT validated by Intel — this is a risk item.
        Search HuggingFace for "eagle3" + "qwen3-14b" or related draft heads.
        If found: convert and test. If NOT found: T-05 is SKIPPED with disposition
        EAGLE3_14B_DRAFT_NOT_AVAILABLE.
      </model>
    </model_inventory>

    <openvino_environment>
      <install_location>C:\Users\mrbla\BlarAI\.venv</install_location>
      <python>C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe (Python 3.11.9)</python>
      <openvino_version>2026.0.0-20965-c6d6a13a886-releases/2026/0</openvino_version>
      <genai_version>2026.0.0.0-2820-dab5b993a38</genai_version>
      <note>
        OpenVINO 2026.0 and GenAI 2026.0 are installed in the BlarAI .venv.
        This is the production environment. Run ALL scripts with the .venv Python.
        Do NOT use any other venv (there is an older ov_venv with 2025.4 — ignore it).
        optimum-intel is also installed in .venv (used by acquire_models.py for INT4 export).
      </note>
    </openvino_environment>

    <constraints>
      <memory_ceiling>31,323 MB effective (ADR-005). Available for LLM agents: ~15,507 MB.</memory_ceiling>
      <memory_warning>When testing Qwen3-14B, set RSS warning threshold to 26,000 MB
        (14B weights ~7.7 GB + KV + runtime may exceed P5-004's 3.9 GB peak by 4×).</memory_warning>
      <privacy>No external network calls during BENCHMARKING. Model download from
        HuggingFace IS authorized during the acquisition phase ONLY.</privacy>
      <power>Must run on AC power. Detect and enforce via psutil before benchmarking.</power>
      <security>Fail-closed on all errors. No partial results treated as success.</security>
      <disk_space>Qwen3-14B INT4 will be ~7.7 GB on disk. Qwen3-8B ~4.3 GB.
        Qwen3-0.6B ~400 MB. Total new disk: ~12.4 GB. Ensure sufficient free space
        before starting acquisition. Check with psutil.disk_usage('C:\\').</disk_space>
    </constraints>
  </context>

  <objective>
    Produce a comprehensive Unified Model Feasibility Matrix that empirically validates
    Qwen3-14B and Qwen3-8B as unified models on the Arc 140V GPU with OpenVINO 2026.0
    optimization features. The 10-test matrix answers the core question:

    **Can Qwen3-14B deliver ≥8 tok/s decode throughput on this hardware, and which
    optimization configuration maximizes performance within the memory budget?**

    Secondary: If 14B fails, does Qwen3-8B meet thresholds as fallback?

    Tertiary: Which speculative decoding path (EAGLE-3 vs standard assisted generation
    with Qwen3-0.6B) delivers better throughput enhancement?
  </objective>

  <execution_plan>

    <phase number="1" name="Environment Setup and Model Acquisition">
      <step>Create branch: feature/p5-feasibility-005-unified-model</step>
      <step>Verify AC power via psutil (fail-closed if on battery)</step>
      <step>Verify openvino_genai importable:
            python -c "import openvino_genai; print(openvino_genai.__version__)"
            Expected: 2026.0.0.0</step>
      <step>Verify optimum-intel importable:
            python -c "from optimum.intel import OVModelForCausalLM; print('OK')"</step>
      <step>Check disk space: require ≥20 GB free on C:\ for models + intermediate files</step>
      <step>Record environment metadata: OS, Python, openvino, genai, optimum-intel versions,
            available devices list (ov.Core().available_devices), AC power status, free disk</step>

      <model_acquisition>
        <description>
          Create script: phase2_gates/scripts/acquire_p5_005_models.py
          This script downloads and quantizes all models needed for the 10-test matrix.
          Pattern it after the existing acquire_models.py but with updated quantization configs.
        </description>

        <model name="Qwen3-14B" priority="1">
          <source>Qwen/Qwen3-14B from HuggingFace (via optimum-intel)</source>
          <method>
            from optimum.intel import OVModelForCausalLM
            model = OVModelForCausalLM.from_pretrained(
                "Qwen/Qwen3-14B",
                export=True,
                compile=False,
                load_in_4bit=True,
                quantization_config={
                    "bits": 4,
                    "sym": False,
                    "group_size": 128,
                    "ratio": 1.0,
                    "scale_estimation": True,
                    "dataset": "wikitext2",
                },
            )
            model.save_pretrained("models/qwen3-14b/openvino-int4-gpu")
          </method>
          <note>scale_estimation=True and dataset="wikitext2" are the reference config
                for Qwen3 8B+ from the llm-chatbot notebook. This is data-aware quantization
                and will take significantly longer than basic quantization (potentially
                30-120 minutes for 14B).</note>
          <note>The download itself will be ~30 GB (FP16/BF16 HuggingFace weights) and the
                conversion produces ~7.7 GB INT4 output. Ensure sufficient disk space.</note>
          <validation>After export, verify:
            - models/qwen3-14b/openvino-int4-gpu/openvino_model.xml exists
            - models/qwen3-14b/openvino-int4-gpu/openvino_model.bin exists
            - openvino_model.bin size is between 6,500 MB and 9,000 MB
            - Quick inference test: load with LLMPipeline("models/qwen3-14b/openvino-int4-gpu", "GPU"),
              generate 10 tokens from a short prompt. Confirm non-empty output.
            - Record SHA-256 of openvino_model.bin</validation>
          <skip_if_cached>If models/qwen3-14b/openvino-int4-gpu/openvino_model.xml AND
            openvino_model.bin both exist, skip download/conversion. Log "cached" and validate.</skip_if_cached>
        </model>

        <model name="Qwen3-8B" priority="2">
          <source>Qwen/Qwen3-8B from HuggingFace</source>
          <method>Same pattern as 14B with same quantization_config. Output to
            models/qwen3-8b/openvino-int4-gpu/</method>
          <validation>Same as 14B. Expect openvino_model.bin between 3,500 MB and 5,500 MB.</validation>
          <skip_if_cached>Same pattern.</skip_if_cached>
        </model>

        <model name="Qwen3-0.6B" priority="3">
          <source>Qwen/Qwen3-0.6B from HuggingFace</source>
          <method>
            OVModelForCausalLM.from_pretrained(
                "Qwen/Qwen3-0.6B",
                export=True,
                compile=False,
                load_in_4bit=True,
                quantization_config={
                    "bits": 4,
                    "sym": False,
                    "group_size": 128,
                    "ratio": 1.0,
                },
            )
            Output to models/qwen3-0.6b/openvino-int4-gpu/
          </method>
          <note>No scale_estimation needed for a 0.6B model — it's small and fast to quantize.
                This model is used ONLY as the draft model for standard assisted generation
                in T-09 and T-10.</note>
          <validation>Expect openvino_model.bin between 300 MB and 600 MB.</validation>
        </model>

        <model name="EAGLE-3 Draft Heads" priority="4">
          <description>
            EAGLE-3 speculative decoding requires architecture-specific draft heads. These
            are separate small models trained to predict future tokens for a specific base model.
          </description>
          <investigation_steps>
            1. Search HuggingFace for "eagle3 qwen3" or "eagle-3 qwen3" or "EAGLE3_Qwen3"
            2. Check the OpenVINO model zoo and openvino_notebooks for EAGLE-3 examples
            3. Check if openvino_genai has a built-in EAGLE-3 API:
               python -c "import openvino_genai; help(openvino_genai.draft_model)" or similar
            4. Check the OV 2026.0 release notes reference for EAGLE-3 Qwen3-8B validation details
            5. If draft heads are found on HuggingFace:
               - Download and convert to OpenVINO IR
               - Place in models/eagle3-qwen3-8b/ and/or models/eagle3-qwen3-14b/
            6. If NO draft heads are found for either model:
               - Record EAGLE3_DRAFT_NOT_AVAILABLE for that model's EAGLE-3 test
               - Document the search performed and what was/wasn't found
               - T-05 (14B EAGLE-3) and/or T-07 (8B EAGLE-3) are SKIPPED accordingly
          </investigation_steps>
          <note>EAGLE-3 for Qwen3-8B was validated by Intel in OV 2026.0 release notes.
                The draft head likely exists — search thoroughly. For Qwen3-14B, the draft
                head may NOT exist — this is a known risk from the cross-reference analysis.</note>
        </model>

        <output>
          Script produces: phase2_gates/evidence/p5_005_model_acquisition.json
          Contents: per-model record of HF ID, output path, file sizes, SHA-256 hashes,
          quick inference test result, elapsed time, any errors.
        </output>
      </model_acquisition>
    </phase>

    <phase number="2" name="Benchmark Script Creation">
      <description>
        Create: phase2_gates/scripts/run_p5_feasibility_005.py

        This script executes the 10-test matrix. It should REUSE proven infrastructure
        patterns from run_p5_feasibility_004.py (attached) but add new capabilities for
        the OV 2026.0 features being tested.
      </description>

      <reusable_from_p5_004>
        Copy and adapt these components from run_p5_feasibility_004.py:
        - RssSampler class (threaded peak RSS tracking at 10ms interval)
        - run_single_generation() pattern (TTFT via streaming callback, total latency, TPS, RSS)
        - stats() and summarize_runs() (mean/stddev/p50/p95/p99/min/max distributions)
        - enforce_ac_power_or_fail_closed() (psutil AC power check)
        - normalize_error() (error fingerprinting)
        - make_generation_config() (greedy decoding, max_new_tokens, eos handling)
        - write_json() (atomic JSON evidence output)
        - Warmup/measured run separation (WARMUP_RUNS=2, MEASURED_RUNS=5)
      </reusable_from_p5_004>

      <new_capabilities>
        The following are NEW for P5-005 and must be implemented in the benchmark script:

        <capability name="INT8 KV-Cache">
          <description>Reduces KV-cache memory by 2× (FP16 → INT8). Configured via GenAI pipeline property.</description>
          <implementation>
            Research the openvino_genai API for enabling INT8 KV-cache.
            Likely one of:
            - GenerationConfig property (e.g., kv_cache_precision="i8")
            - Pipeline config at creation time
            - ov_genai.LLMPipeline property
            Consult openvino_genai Python binding docs / help() for the exact API.
            If the API does not exist in 2026.0, record INT8_KV_NOT_AVAILABLE and skip
            tests T-02, T-03, T-04, T-08.
          </implementation>
        </capability>

        <capability name="XAttention (Block Sparse Attention)">
          <description>Xe2 preview feature for improved TTFT. Configured via OpenVINO runtime property.</description>
          <implementation>
            Research the OpenVINO 2026.0 API for XAttention on Xe2 GPU.
            Likely configured via:
            - core.set_property("GPU", {"XATTENTION_ENABLE": True}) or similar
            - Pipeline config property at creation time
            Check OV 2026.0 release notes or help(ov.Core) for the property name.
            If not available or not applicable via GenAI pipeline, record
            XATTENTION_NOT_AVAILABLE and skip tests T-03, T-04, T-08.
          </implementation>
        </capability>

        <capability name="Prefix Caching">
          <description>Caches KV states for repeated prompt prefixes (e.g., system prompts).
            Eliminates redundant prefill computation.</description>
          <implementation>
            Research the openvino_genai API for prefix caching.
            Likely configured via GenerationConfig or pipeline config.
            Check: python -c "import openvino_genai; help(openvino_genai.GenerationConfig)"
            If not available, record PREFIX_CACHING_NOT_AVAILABLE and note impact on T-04, T-08.
          </implementation>
        </capability>

        <capability name="EAGLE-3 Speculative Decoding">
          <description>Uses a small trained draft head to predict multiple future tokens,
            verified in parallel by the base model. 2-3× throughput with zero quality loss.</description>
          <implementation>
            Research the openvino_genai API for speculative decoding / EAGLE-3.
            Check: help(openvino_genai.LLMPipeline) for draft_model or speculative parameters.
            Also check: openvino_genai.draft_model, openvino_genai.ContinuousBatchingPipeline,
            or similar entry points.
            The draft head model must be in OpenVINO IR format and loaded alongside the base model.
            If the API exists but no draft head model is available: EAGLE3_DRAFT_NOT_AVAILABLE.
            If the API does not exist in this GenAI version: EAGLE3_API_NOT_AVAILABLE.
          </implementation>
        </capability>

        <capability name="Standard Assisted Generation (Qwen3-0.6B Draft)">
          <description>Non-EAGLE-3 speculative decoding path. Uses a full (but small) LLM
            as a standalone draft model. The draft model autoregressively generates N candidate
            tokens, then the base model verifies them in a single forward pass.
            Lower acceptance rate than EAGLE-3 but requires only a generic small model,
            not architecture-specific draft heads.</description>
          <implementation>
            Research the openvino_genai API for assisted generation / speculative decoding
            using a standalone draft model (NOT EAGLE-3 draft heads).
            The pattern is typically:
              draft_pipe = ov_genai.LLMPipeline(draft_model_path, "GPU")
              main_pipe = ov_genai.LLMPipeline(main_model_path, "GPU")
              # Some API to link them for assisted generation
            Check openvino_genai docs for: assisted_generation, draft_model, speculative.
            If NO assisted generation API exists for standalone draft models in this version,
            record ASSISTED_GEN_NOT_AVAILABLE and skip T-09, T-10.
          </implementation>
        </capability>
      </new_capabilities>

      <test_matrix name="10-Test Unified Model Feasibility Matrix">
        <description>
          Each test is a CONFIGURATION (model + features). For each configuration, run
          across the PROMPT BAND sweep to produce a latency/throughput/memory profile.
        </description>

        <prompt_bands values="128, 256, 512, 1024, 2048, 3072, 4096">
          <note>These are USER TOKEN counts (approximate). Build prompts using Qwen3 chat
            template. Pad user content with repeated filler text to reach target length.
            Read chat_template from the tokenizer config in the model directory.</note>
          <note>4096 is the current production context ceiling. Testing through 4096
            validates the full operational range.</note>
        </prompt_bands>

        <per_point_protocol>
          - WARMUP_RUNS = 2 (discarded — pipeline warmup and JIT compilation)
          - MEASURED_RUNS = 5 (recorded for statistics)
          - MAX_NEW_TOKENS = 128 (fixed output length for comparable measurement)
          - temperature = 0.0 (greedy decoding for reproducibility)
        </per_point_protocol>

        <test id="T-01" name="14B Baseline" model="qwen3-14b" device="GPU">
          <features>None (FP16 KV-cache, no speculative decoding, no XAttention, no prefix caching)</features>
          <purpose>Establish raw Qwen3-14B decode throughput on GPU. This is THE critical measurement
            that validates or invalidates the 8-9.5 tps extrapolation from the cross-reference analysis.</purpose>
          <gate_relevance>G-01 (Primary Threshold), G-03 (Memory), G-04 (Stability)</gate_relevance>
          <pipeline_creation>
            pipe = ov_genai.LLMPipeline("models/qwen3-14b/openvino-int4-gpu", "GPU")
          </pipeline_creation>
        </test>

        <test id="T-02" name="14B + INT8 KV" model="qwen3-14b" device="GPU">
          <features>INT8 KV-cache enabled</features>
          <purpose>Measure impact of INT8 KV-cache on memory and throughput. Expected: lower memory,
            potentially slightly faster decode due to reduced memory bandwidth for KV reads.</purpose>
          <gate_relevance>G-03 (Memory — expect improvement), G-04 (Stability)</gate_relevance>
          <dependency>Requires INT8 KV API to be available. If not: SKIP.</dependency>
        </test>

        <test id="T-03" name="14B + INT8 KV + XAttention" model="qwen3-14b" device="GPU">
          <features>INT8 KV-cache + XAttention (Block Sparse Attention)</features>
          <purpose>Measure combined impact. XAttention should primarily improve TTFT (prefill phase).
            Combined with INT8 KV for maximum infrastructure optimization before speculative decoding.</purpose>
          <gate_relevance>G-01 (if TTFT improves meaningfully), G-03, G-04</gate_relevance>
          <dependency>Requires both INT8 KV and XAttention APIs. If either unavailable: SKIP.</dependency>
        </test>

        <test id="T-04" name="14B Full Optimization Stack" model="qwen3-14b" device="GPU">
          <features>INT8 KV-cache + XAttention + Prefix Caching</features>
          <purpose>Maximum non-speculative optimization for Qwen3-14B. This is the best possible
            throughput WITHOUT draft models or speculative decoding.</purpose>
          <gate_relevance>G-01, G-03, G-04. This config is the strong candidate for production
            deployment if speculative decoding is unavailable or unreliable.</gate_relevance>
          <dependency>Requires INT8 KV + XAttention + prefix caching APIs. Skip missing features
            but still run with whatever IS available.</dependency>
          <prefix_caching_protocol>
            For prefix caching: use the SAME system prompt across all prompt bands in this test.
            Run band 128 first (populates prefix cache), then 256, 512, etc.
            TTFT at band 256+ should be measurably lower than T-03 at the same bands
            if prefix caching is working.
          </prefix_caching_protocol>
        </test>

        <test id="T-05" name="14B + EAGLE-3" model="qwen3-14b" device="GPU">
          <features>EAGLE-3 speculative decoding (requires Qwen3-14B-specific draft head)</features>
          <purpose>Test the highest-throughput path for Qwen3-14B. If EAGLE-3 works,
            expected 2-3× throughput improvement (16-28 tps). This is the optimal production config.</purpose>
          <gate_relevance>G-02 (Speculative Decoding), G-01 (if dramatically improves tps)</gate_relevance>
          <dependency>Requires EAGLE-3 draft head for Qwen3-14B AND the GenAI EAGLE-3 API.
            If EITHER is unavailable: SKIP with EAGLE3_14B_NOT_AVAILABLE.
            This is a KNOWN RISK — Intel has NOT validated EAGLE-3 for Qwen3-14B.</dependency>
        </test>

        <test id="T-06" name="8B Baseline" model="qwen3-8b" device="GPU">
          <features>None (FP16 KV-cache, no speculative decoding)</features>
          <purpose>Establish raw Qwen3-8B decode throughput on GPU. Validates the 14-17 tps
            extrapolation. This is the FALLBACK measurement — used only if 14B fails G-01.</purpose>
          <gate_relevance>G-01 fallback, G-03, G-04</gate_relevance>
          <pipeline_creation>
            pipe = ov_genai.LLMPipeline("models/qwen3-8b/openvino-int4-gpu", "GPU")
          </pipeline_creation>
        </test>

        <test id="T-07" name="8B + EAGLE-3" model="qwen3-8b" device="GPU">
          <features>EAGLE-3 speculative decoding (Intel-validated for Qwen3-8B in OV 2026.0)</features>
          <purpose>This SHOULD work — Intel validated it. Expected 28-50 tps.
            Establishes the upper bound for the fallback model path.</purpose>
          <gate_relevance>G-02 (Speculative Decoding), G-01 fallback</gate_relevance>
          <dependency>Requires EAGLE-3 draft head for Qwen3-8B AND the GenAI EAGLE-3 API.
            If unavailable: SKIP. But this is EXPECTED to be available per OV 2026.0 release.</dependency>
        </test>

        <test id="T-08" name="8B Full Optimization Stack" model="qwen3-8b" device="GPU">
          <features>INT8 KV-cache + XAttention + Prefix Caching</features>
          <purpose>Maximum non-speculative optimization for the fallback model.
            Parallel to T-04 for the 14B model. Establishes the best configs for
            Qwen3-8B if EAGLE-3 is unavailable.</purpose>
          <gate_relevance>G-01 fallback, G-03, G-04</gate_relevance>
          <dependency>Same as T-04 — use whatever features ARE available.</dependency>
        </test>

        <test id="T-09" name="14B + Qwen3-0.6B Assisted Generation" model="qwen3-14b" device="GPU">
          <features>Standard assisted generation with Qwen3-0.6B as standalone draft model</features>
          <purpose>Alternative to EAGLE-3 for Qwen3-14B speculative decoding. Uses a full
            small LLM (Qwen3-0.6B) as the draft model instead of architecture-specific draft heads.
            Lower expected speedup than EAGLE-3 (1.3-2× vs 2-3×) but no draft-head dependency.
            This is the CONTINGENCY PATH if EAGLE-3 is unavailable for 14B.</purpose>
          <gate_relevance>G-05a (14B Assisted Generation), G-01 (if meaningful tps improvement)</gate_relevance>
          <dependency>Requires openvino_genai assisted generation API for standalone draft models.
            If API not available: SKIP with ASSISTED_GEN_NOT_AVAILABLE.</dependency>
          <note>Both the main model AND the draft model consume GPU memory simultaneously.
            14B weights (~7.7 GB) + 0.6B weights (~400 MB) + KV-caches for both.
            Monitor RSS carefully — this is the highest-memory configuration in the matrix.</note>
        </test>

        <test id="T-10" name="8B + Qwen3-0.6B Assisted Generation" model="qwen3-8b" device="GPU">
          <features>Standard assisted generation with Qwen3-0.6B as standalone draft model</features>
          <purpose>Fallback assisted generation path. 8B + 0.6B draft.
            Expected throughput improvement of 1.3-2× over T-06 baseline.</purpose>
          <gate_relevance>G-05b (8B Assisted Generation), G-01 fallback</gate_relevance>
          <dependency>Same as T-09 — requires assisted generation API.</dependency>
        </test>
      </test_matrix>

      <per_run_measurements>
        <metric name="ok" type="bool">Did the run complete without error?</metric>
        <metric name="latency_first_token_ms" type="float">Time to first generated token (TTFT)</metric>
        <metric name="latency_total_ms" type="float">Total wall-clock generation time</metric>
        <metric name="tokens_generated" type="int">Number of tokens actually produced</metric>
        <metric name="decode_tokens_per_sec" type="float">Generation throughput (tokens / decode time)</metric>
        <metric name="rss_before_mb" type="float">Process RSS before inference (via psutil)</metric>
        <metric name="rss_peak_mb" type="float">Peak RSS during inference (via RssSampler thread)</metric>
        <metric name="rss_after_mb" type="float">Process RSS after inference</metric>
        <metric name="error" type="string_or_null">Error message if failed, null if success</metric>
        <metric name="error_fingerprint" type="string_or_null">Normalized error category</metric>
      </per_run_measurements>

      <implementation_guidance>
        <note>Use openvino_genai.LLMPipeline(model_dir, "GPU") for all tests. GPU is the only
          target device for this milestone. Do NOT test NPU or CPU.</note>
        <note>For Qwen3 chat template: read the tokenizer_config.json or chat_template.jinja
          from the model directory. Qwen3 uses a different template than Qwen2.5.
          Typical Qwen3 format:
          &lt;|im_start|&gt;system\n{system_prompt}&lt;|im_end|&gt;\n
          &lt;|im_start|&gt;user\n{user_content}&lt;|im_end|&gt;\n
          &lt;|im_start|&gt;assistant\n
          Verify from the actual model's tokenizer config.</note>
        <note>Load each test configuration ONCE (create pipeline), run ALL prompt bands on it,
          then UNLOAD (del pipe; gc.collect()) before creating the next test's pipeline.
          This prevents memory stacking between tests.</note>
        <note>Wrap every inference call in try/except. Record errors but continue to next point.
          A failure at one prompt band is DATA, not a crash.</note>
        <note>If a pipeline CREATION fails (e.g., out of memory loading 14B), record as a
          pipeline_creation_error for that test and move to the next test.</note>
        <note>For speculative decoding tests (T-05, T-07, T-09, T-10): if the API call
          fails with an unsupported-feature error, record the exact error message and
          mark the test as SKIPPED with the specific reason. These features are experimental.</note>
        <note>If a feature API (INT8 KV, XAttention, prefix caching) is discovered during
          implementation to not exist or not apply to the GenAI LLMPipeline, adapt:
          - Still run the test with whatever features ARE available
          - Document which features were available and which were not
          - The test becomes a partial test measuring the available feature subset</note>
        <note>Run tests in order T-01 through T-10. This ensures baseline measurements
          come first, enabling early abort if the baseline itself fails catastrophically.</note>
      </implementation_guidance>
    </phase>

    <phase number="3" name="Run the Benchmark">
      <step>Run the benchmark script on AC power with no other heavy processes.</step>
      <step>Script produces: phase2_gates/evidence/p5_unified_model_feasibility_matrix.json</step>
      <step>Expected runtime estimate:
        - Model loading: ~20-60 seconds per pipeline creation (GPU compilation)
        - Per test: 7 prompt bands × (2 warmup + 5 measured) × ~2-10 seconds per run
        - 10 tests total: ~60-120 minutes for the full benchmark
        - If speculative decoding tests are skipped, subtract ~20-30 minutes
      </step>
      <step>Monitor during execution:
        - Watch for RSS approaching memory_warning threshold (26,000 MB)
        - Watch for pipeline creation failures (especially for 14B model)
        - If the first test (T-01) cannot even load the model, this is a CRITICAL failure
          that invalidates the memory projections — record and stop
      </step>
      <step>If the benchmark script crashes mid-execution:
        - Check the partial evidence JSON (use atomic writes so partial data is preserved)
        - Identify which test/band caused the crash
        - Fix the issue and re-run from the failed point (skip-if-cached for completed tests)
      </step>
    </phase>

    <phase number="4" name="Analysis and Decision Artifacts">
      <step>Produce synthesis document: docs/FEASIBILITY_UNIFIED_MODEL.md</step>

      <summary_document_structure>
        <section name="1. Model Acquisition Results">
          For each model acquired:
          - HuggingFace source, quantization config applied, output path
          - File sizes (openvino_model.bin)
          - SHA-256 hashes
          - Quick inference validation result
          - Acquisition time (download + quantization)
          - Any issues encountered
        </section>

        <section name="2. EAGLE-3 / Assisted Generation API Investigation Results">
          Document the search for EAGLE-3 draft heads and assisted generation APIs:
          - What was searched (HuggingFace queries, API exploration, docs consulted)
          - What was found / not found
          - Which tests are available vs skipped, and why
          - If a speculative decoding API was found but untested by Intel for 14B: note risk.
        </section>

        <section name="3. Qwen3-14B Results (T-01 through T-05, T-09)">
          For each test:
          - Configuration summary (features enabled)
          - Throughput table per prompt band (mean/p50/p95 tps)
          - TTFT table per prompt band (mean/p50/p95 ms)
          - Peak RSS table per prompt band
          - Pass/fail per band
          - Feature availability notes (was the feature actually usable?)

          Cross-test comparison table at key prompt bands (512, 2048, 4096):
          | Test | Config | TPS @ 512 | TPS @ 2048 | TPS @ 4096 | Peak RSS |
          Show the incremental effect of each optimization feature.
        </section>

        <section name="4. Qwen3-8B Results (T-06 through T-08, T-10)">
          Same structure as Section 3 but for the fallback model.
        </section>

        <section name="5. Cross-Model Comparison">
          Side-by-side 14B vs 8B at matching configurations:
          | Metric | 14B Baseline | 8B Baseline | 14B Best Config | 8B Best Config |
          Throughput, memory, TTFT.
          Quality note: both are general-purpose instruction models. No formal quality
          benchmark in this milestone — quality is assessed from HuggingFace benchmarks.
        </section>

        <section name="6. Speculative Decoding Comparison">
          If both EAGLE-3 and standard assisted generation were testable:
          | Path | Speedup vs Baseline | Extra Memory | Draft Model Required |
          Recommend which speculative path to use in production.
        </section>

        <section name="7. Production Configuration Recommendation">
          Based on ALL data, recommend:
          A. PRIMARY model + configuration for production deployment
          B. FALLBACK model + configuration
          C. Speculative decoding path (EAGLE-3 vs assisted gen vs none)
          D. Expected production throughput (tps range)
          E. Expected production memory (total MB)
          F. Any OV features that were NOT available and should be re-evaluated in future OV releases
        </section>

        <section name="8. Disposition">
          One of:
          - QWEN3_14B_CONFIRMED: 14B meets ≥8 tps threshold. Recommended config: [config].
            Proceed with ADR update and production integration.
          - QWEN3_14B_WITH_SPEC_DECODING: 14B meets ≥8 tps ONLY with speculative decoding.
            Speculative decoding is a hard dependency. Config: [config].
          - QWEN3_14B_MARGINAL: 14B is between 6-8 tps. Consider 8B fallback or accept
            marginal performance. Decision deferred to Lead Architect.
          - QWEN3_8B_FALLBACK: 14B below 6 tps. Recommend Qwen3-8B as unified model.
            Config: [config]. Trade-off: lower quality, higher throughput.
          - QWEN3_8B_WITH_EAGLE3: Fallback to 8B + validated EAGLE-3 path.
          - BOTH_INFEASIBLE: Neither model meets minimum thresholds on this hardware.
            Architectural re-evaluation required.
          - INSUFFICIENT_EVIDENCE: Critical tests could not run (model load failure,
            API unavailability). Specify what is missing.
        </section>
      </summary_document_structure>
    </phase>

    <phase number="5" name="Commit and Ledger Update">
      <step>Stage and commit all new/modified files:
        - phase2_gates/scripts/acquire_p5_005_models.py
        - phase2_gates/scripts/run_p5_feasibility_005.py
        - phase2_gates/evidence/p5_005_model_acquisition.json
        - phase2_gates/evidence/p5_unified_model_feasibility_matrix.json
        - docs/FEASIBILITY_UNIFIED_MODEL.md
        - docs/POST_OPERATIONAL_MATURATION_LEDGER.md (updated)
        - docs/IMPLEMENTATION_PLAN.md (updated)
        - Any new model directories created under models/
      </step>

      <step>Do NOT commit model weight files (openvino_model.bin) to git.
        Add to .gitignore if not already excluded:
          models/qwen3-14b/
          models/qwen3-8b/
          models/qwen3-0.6b/
          models/eagle3-*/
        Commit the .gitignore update.</step>

      <step>Update docs/POST_OPERATIONAL_MATURATION_LEDGER.md — append P5-FEASIBILITY-005 entry
        following the format of the P5-004 entry (already in the file).</step>

      <step>Update docs/IMPLEMENTATION_PLAN.md — append section 1.10 with P5-005 snapshot.</step>

      <step>Commit template:
        "P5-FEASIBILITY-005: unified model feasibility matrix [DISPOSITION]"
        where [DISPOSITION] is the outcome from Section 8 of the synthesis document.</step>
    </phase>

  </execution_plan>

  <quality_gate name="Unified Model Feasibility Gate (UMFG)">
    <description>
      This gate evaluates whether empirical evidence is sufficient to select a unified
      model and configuration for production. Some tests being SKIPPED (due to API
      unavailability) does NOT automatically fail the gate — the required checks below
      distinguish between essential and enhancement tests.
    </description>

    <checks>
      <check id="G-01" name="Primary Throughput Threshold" required="true">
        Qwen3-14B T-01 (baseline) OR Qwen3-14B with any optimization (T-02/T-03/T-04)
        must achieve MEAN decode throughput ≥8.0 tps at prompt band 512.
        If 14B fails across ALL configs: check Qwen3-8B T-06 as fallback.
        If 8B ALSO fails: BOTH_INFEASIBLE.
        CRITICAL: This is the single most important measurement in the entire milestone.
      </check>
      <check id="G-02" name="Speculative Decoding Viability" required="false">
        At least ONE speculative decoding test (T-05, T-07, T-09, or T-10) must complete
        successfully and show measurable throughput improvement (≥1.3× over the corresponding
        baseline test).
        If ALL speculative tests are SKIPPED or show no improvement: SPEC_DECODING_NOT_VIABLE.
        This does NOT fail the overall gate — it means production deploys without spec decoding.
      </check>
      <check id="G-03" name="Memory Budget Compliance" required="true">
        Peak RSS for the PRIMARY recommended config must not exceed 15,507 MB
        (the available-for-agents budget from the cross-reference analysis).
        For speculative decoding configs (which load two models), peak RSS must not
        exceed 15,507 MB with BOTH models loaded.
        If memory is exceeded: that config is eliminated but others may still pass.
      </check>
      <check id="G-04" name="Stability" required="true">
        The PRIMARY recommended config must produce ≥4/5 valid runs (no errors)
        at EVERY prompt band from 128 through 4096.
        Sporadic failures at a single band are acceptable (4/5 minimum).
        Systematic failures across multiple bands → UNSTABLE.
      </check>
      <check id="G-05a" name="14B Assisted Generation" required="false">
        T-09 (14B + Qwen3-0.6B draft) produces measurable speedup.
        SKIPPED if assisted generation API is not available.
      </check>
      <check id="G-05b" name="8B Assisted Generation" required="false">
        T-10 (8B + Qwen3-0.6B draft) produces measurable speedup.
        SKIPPED if assisted generation API is not available.
      </check>
      <check id="G-06" name="Cross-Test Comparability" required="true">
        At least 3 tests must produce valid results at prompt band 512,
        enabling meaningful cross-configuration comparison.
        If fewer than 3 tests complete: INSUFFICIENT_EVIDENCE.
      </check>
    </checks>

    <disposition_rules>
      <rule>If G-01 PASS (14B ≥8 tps) + G-03 PASS + G-04 PASS + G-06 PASS →
        Disposition from Section 8 based on which config was best.</rule>
      <rule>If G-01 FAIL for 14B but PASS for 8B + G-03 + G-04 + G-06 →
        QWEN3_8B_FALLBACK or QWEN3_8B_WITH_EAGLE3 (depending on G-02).</rule>
      <rule>If G-01 FAIL for both models → BOTH_INFEASIBLE.</rule>
      <rule>If G-03 FAIL for all configs → Memory budget violated. Re-assess budget or
        consider smaller model (Qwen3-4B or Qwen2.5-7B as emergency fallback).</rule>
      <rule>If G-06 FAIL → INSUFFICIENT_EVIDENCE. Too few tests completed to decide.</rule>
      <rule>G-02, G-05a, G-05b are ENHANCEMENT gates. Their failure does not block
        the overall disposition — it only affects which config is recommended.</rule>
    </disposition_rules>

    <decision_tree>
      Step 1: Does T-01 (14B baseline) achieve ≥8 tps mean at band 512?
        YES → 14B is PRIMARY. Proceed to Step 2.
        NO  → Does any T-02/T-03/T-04 achieve ≥8 tps mean at band 512?
          YES → 14B viable WITH that optimization. Config noted. Proceed to Step 2.
          NO  → 14B FAILS. Go to Step 3.

      Step 2: Does speculative decoding (T-05/T-09) improve 14B throughput ≥1.3×?
        YES → Best spec-decoding config is primary recommendation.
        NO  → Best non-speculative config (T-01/T-02/T-03/T-04) is primary rec.
        Either way → Record 14B disposition. Also record 8B results for reference.

      Step 3 (14B failed): Does T-06 (8B baseline) achieve ≥8 tps mean at band 512?
        YES → 8B is FALLBACK. Does T-07/T-10 improve throughput?
          YES → 8B + spec-decoding is recommendation.
          NO  → 8B baseline or 8B + optimization stack (T-08) is recommendation.
        NO  → BOTH_INFEASIBLE. Neither model meets threshold on this hardware.
    </decision_tree>
  </quality_gate>

  <rules>
    <rule>Execute phases sequentially. Do not skip phases.</rule>
    <rule>Model acquisition (Phase 1) requires HuggingFace network access. This is the
      ONLY phase where network access is authorized. All other phases are fully local.</rule>
    <rule>Record ALL results — failures and SKIPs are data, not errors to hide.</rule>
    <rule>Do not modify any production code (services/, shared/, launcher/).</rule>
    <rule>Do not modify existing evidence files from prior milestones.</rule>
    <rule>AC power enforcement is mandatory during benchmarking (Phase 3). Model acquisition
      (Phase 1) does not require AC power enforcement.</rule>
    <rule>Unload each model pipeline before loading the next to prevent memory stacking.
      Use: del pipe; gc.collect(); time.sleep(2)</rule>
    <rule>If a model fails to load on GPU, record as pipeline_creation_error and continue.</rule>
    <rule>Use greedy decoding (temperature=0) for all benchmark runs.</rule>
    <rule>GPU is the ONLY target device. Do NOT test NPU or CPU in this milestone.</rule>
    <rule>All scripts run with: C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe</rule>
    <rule>Commit on branch feature/p5-feasibility-005-unified-model, not main.</rule>
    <rule>Do NOT commit model weight files (.bin) to git. Update .gitignore accordingly.</rule>
    <rule>Stop after Phase 5. Do not start unrequested work.</rule>
    <rule>If quantization of Qwen3-14B takes longer than 3 hours, record partial progress
      and note the elapsed time. Do not abandon — quantization of large models can be slow.</rule>
    <rule>The Qwen3-0.6B model is ONLY used as a draft model for T-09 and T-10. Do NOT
      benchmark it as a standalone model — it is too small for any BlarAI agent role.</rule>
  </rules>

</execution_prompt>
```
