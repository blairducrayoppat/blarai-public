---
title: P5_FEASIBILITY_004_PROMPT
status: archived
area: portfolio
---

# P5-FEASIBILITY-004 Execution Prompt

Paste the XML block below into a new Execution Agent chat session along with the listed attachments.

---

## Required Attachments

1. `.github/copilot-instructions.md`
2. `shared/constants.py`
3. `docs/POST_OPERATIONAL_MATURATION_LEDGER.md`
4. `docs/FEASIBILITY_CONTEXT_WINDOW.md`
5. `phase2_gates/evidence/p5_runtime_ceiling_characterization.json` (first 200 lines)
6. `phase2_gates/evidence/p5_input_length_latency_matrix.json` (first 200 lines)
7. `services/assistant_orchestrator/src/npu_inference.py` (lines 360-410 for LLMPipeline config)
8. `services/policy_agent/src/gpu_inference.py` (lines 1-80 for reference pattern)

---

## Key Discovery (from Official OpenVINO Documentation)

The "1,024-token wall" that blocked all three prior feasibility studies is **NOT a hardware
limit** — it is a **software default** that can be raised via configuration.

Source: https://docs.openvino.ai/2025/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html

Key facts from the official docs:
- `MAX_PROMPT_LEN` — configurable pipeline parameter, **defaults to 1024**, can be set higher
- `MIN_RESPONSE_LEN` — configurable, **defaults to 128**, can be set higher
- **Total NPU context size** = MAX_PROMPT_LEN + MIN_RESPONSE_LEN (default: 1152)
- `PREFILL_HINT: DYNAMIC` — available since OpenVINO 2025.3 (default since 2025.3),
  enables dynamic prompt execution that **supports longer prompts**
- `NPUW_LLM_PREFILL_CHUNK_SIZE` — controls dynamic chunking (default: 1024).
  When MAX_PROMPT_LEN > chunk size, dynamic chunking activates automatically.
- `GENERATE_HINT: BEST_PERF` — ensures best performance at cost of compilation speed
- OpenVINO 2026.0 has been released with further NPU improvements and speculative decoding on NPU.

The current production code (`npu_inference.py` lines 371-381) does NOT set MAX_PROMPT_LEN
or MIN_RESPONSE_LEN — it only passes `PERFORMANCE_HINT` and `MODEL_PRIORITY`. This means
the NPU has been running with the **default 1024-token limit** that can be raised.

The error messages from P5-002/003 literally say:
> "Set the 'MAX_PROMPT_LEN' config option to increase the limit."

**Installed version:** OpenVINO 2026.0.0 / GenAI 2026.0.0.0 (in the BlarAI `.venv`).
This is well past 2025.3 — `PREFILL_HINT: DYNAMIC` is available and is the default.
OpenVINO 2026.0 adds further NPU improvements including speculative decoding support.

---

## XML Execution Prompt

```xml
<execution_prompt milestone="P5-FEASIBILITY-004" type="empirical_evidence_collection">

  <context>
    <summary>
      Three prior feasibility studies (P5-001, P5-002, P5-003) investigated whether the
      context window can be expanded beyond 4,096 tokens. All three tested ONLY the NPU
      and all three hit the same wall: the OpenVINO stateful NPU pipeline refused prompts
      exceeding 1,024 formatted tokens. The error message said: "Set the 'MAX_PROMPT_LEN'
      config option to increase the limit."

      CRITICAL DISCOVERY: The 1,024-token limit is NOT a hardware ceiling — it is a
      SOFTWARE DEFAULT (MAX_PROMPT_LEN=1024) that can be configured higher when creating
      the LLMPipeline. The official OpenVINO docs explicitly state this is configurable
      and that "a larger MAX_PROMPT_LEN" may be needed for chat scenarios.

      The current production code (npu_inference.py) never sets MAX_PROMPT_LEN — it uses
      the default. All previous feasibility test scripts also used the default.

      This milestone has TWO major tasks:
      1. Test the NPU with INCREASED MAX_PROMPT_LEN values (2048, 3072, 4096, 6144, 8192)
         to find the REAL hardware/memory limit — not the software default.
      2. Test the GPU and CPU for GENERATION workloads (they have never been tested for this)
         to build a complete device capability map.

      Qwen3-1.7B is NOT supported on the NPU by Intel. It must only be tested on GPU and CPU.
    </summary>

    <prior_evidence>
      <study id="P5-001" disposition="DO-NOT-EXPAND" type="analytical">
        Analytical study only. Concluded DO-NOT-EXPAND based on NPU memory projections.
        Did not test GPU or CPU. Did not configure MAX_PROMPT_LEN. Did not discover it
        was configurable.
      </study>
      <study id="P5-002" disposition="NO_DECISION" type="empirical">
        NPU-only. 512-token band succeeded (30/30 runs). 1024+ all failed (0/30 valid).
        NEVER SET MAX_PROMPT_LEN — all failures were due to the 1024-token software default.
        The error message literally said to increase MAX_PROMPT_LEN.
      </study>
      <study id="P5-003" disposition="NO_DECISION" type="empirical">
        NPU-only ceiling characterization. All bands >=768 user tokens failed.
        NEVER SET MAX_PROMPT_LEN — same software default caused all failures.
      </study>
    </prior_evidence>

    <hardware_inventory>
      <device name="NPU" chip="Intel AI Boost (Lunar Lake)">
        Current role: Assistant Orchestrator generation.
        KNOWN SOFTWARE DEFAULT: MAX_PROMPT_LEN=1024 (not set in production code).
        UNKNOWN: What happens when MAX_PROMPT_LEN is raised? What is the REAL ceiling?
        Available config options (OpenVINO 2025.3+):
          - MAX_PROMPT_LEN: int (default 1024, RAISE THIS)
          - MIN_RESPONSE_LEN: int (default 128)
          - PREFILL_HINT: "DYNAMIC" (default in 2025.3+) or "STATIC"
          - GENERATE_HINT: "FAST_COMPILE" (default) or "BEST_PERF"
          - NPUW_LLM_PREFILL_CHUNK_SIZE: int (default 1024, controls dynamic chunking)
      </device>
      <device name="GPU" chip="Intel Arc 140V (Xe2, 8 Xe-cores, 128 XMX)">
        Current role: Policy Agent classification only (short prompts, 78ms).
        Generation capability: UNTESTED. No static-shape MAX_PROMPT_LEN constraint.
        Uses openvino_genai.LLMPipeline(model_dir, "GPU").
        Dynamic quantization enabled by default on XMX hardware since OpenVINO 2025.2.
      </device>
      <device name="CPU" chip="Intel Core Ultra 7 258V (4P+4E cores, 8 threads)">
        Current role: Not used for model inference.
        Generation capability: UNTESTED. No static-shape constraint.
        Can use openvino_genai.LLMPipeline(model_dir, "CPU").
      </device>
    </hardware_inventory>

    <model_inventory>
      <model name="qwen2.5-1.5b-instruct" path="models/qwen2.5-1.5b-instruct/openvino-int4-npu"
             params="1.5B" quant="INT4-MIXED" size_mb="976" status="PRODUCTION">
        Currently used by PA (GPU) and AO (NPU). Same weights, different device targets.
        OpenVINO GenAI LLMPipeline compiles for the specified device at load time.
        Test on: NPU (with raised MAX_PROMPT_LEN), GPU, CPU.
      </model>
      <model name="qwen3-1.7b" params="1.7B" quant="INT4" status="AVAILABLE_UNTESTED">
        <variant path="models/qwen3-1.7b/openvino-int4" target="CPU/GPU generic" />
        NOTE: Qwen3 is NOT supported on the NPU by Intel. Do NOT test qwen3 on NPU.
        Test on: GPU and CPU ONLY.
      </model>
    </model_inventory>

    <openvino_environment>
      <install_location>C:\Users\mrbla\BlarAI\.venv</install_location>
      <openvino_version>2026.0.0-20965-c6d6a13a886-releases/2026/0</openvino_version>
      <genai_version>2026.0.0.0-2820-dab5b993a38</genai_version>
      <note>OpenVINO 2026.0 and GenAI 2026.0 are installed in the BlarAI .venv.
            This is the production environment. Run the benchmark with the default
            .venv Python: C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe
            (There is also an older ov_venv with 2025.4 — do NOT use it.)</note>
    </openvino_environment>

    <constraints>
      <memory_ceiling>31.323 GB effective (ADR-005). Process RSS budget ~3.5 GB observed at 512 tokens.</memory_ceiling>
      <privacy>No external network calls. All inference local.</privacy>
      <power>Must run on AC power. Detect and enforce via psutil before benchmarking.</power>
      <security>Fail-closed on all errors. No partial results treated as success.</security>
    </constraints>
  </context>

  <objective>
    Produce a comprehensive Device × Model × Config × Prompt-Length capability matrix that answers:
    1. NPU with raised MAX_PROMPT_LEN: How far can the NPU actually go? Test 2048, 3072, 4096, 6144, 8192.
       What is the REAL limit when you configure it properly?
    2. GPU for generation: How fast and how far can the GPU go for text generation (not just PA classification)?
    3. CPU for generation: Same question for CPU — what are its limits and speed?
    4. Qwen3-1.7B on GPU/CPU: Does the newer model perform better or worse than Qwen2.5?
    5. Final answer: What is the best device (or device combination) for each context window size?
  </objective>

  <execution_plan>

    <phase number="1" name="Environment Setup and Validation">
      <step>Create branch: feature/p5-feasibility-004-multi-device</step>
      <step>Verify AC power via psutil (fail-closed if on battery)</step>
      <step>Ensure openvino_genai is importable from the BlarAI .venv Python.
            OpenVINO 2026.0 and GenAI 2026.0 are already installed in the .venv.
            Verify with: python -c "import openvino_genai; print(openvino_genai.__version__)"</step>
      <step>Verify all model directories exist and contain openvino_model.xml + openvino_model.bin</step>
      <step>Record environment metadata: OS, Python version, openvino version,
            openvino_genai version, available devices list</step>
    </phase>

    <phase number="2" name="Multi-Device Generation Benchmark Script">
      <description>
        Create a single benchmark script: phase2_gates/scripts/run_p5_feasibility_004.py
        This script tests GENERATION on all 3 devices, with NPU using raised MAX_PROMPT_LEN.
      </description>

      <test_matrix_npu name="Campaign A: NPU with configured MAX_PROMPT_LEN">
        <description>
          The KEY experiment. For each MAX_PROMPT_LEN value, create a FRESH LLMPipeline
          with that config, then test prompts up to that length.
        </description>
        <dimension name="model" values="qwen2.5-1.5b-instruct ONLY (qwen3 NOT supported on NPU)" />
        <dimension name="max_prompt_len_config" values="1024, 2048, 3072, 4096, 6144, 8192" />
        <dimension name="min_response_len_config" values="512" note="Fixed to allow reasonable generation" />
        <dimension name="prompt_length_user_tokens"
                   note="For each MAX_PROMPT_LEN config, test: 256, 512, then values approaching the configured max.
                         E.g. for MAX_PROMPT_LEN=2048: test 256, 512, 1024, 1536, 1800, 2000.
                         For MAX_PROMPT_LEN=4096: test 256, 512, 1024, 2048, 3072, 3800." />
        <fixed name="output_tokens" value="128" note="Fixed output for comparable measurement" />
        <fixed name="runs_per_point" value="5" note="5 measured runs (2 warmup discarded)" />
        <fixed name="temperature" value="0.0" note="Greedy decoding for reproducibility" />
        <pipeline_config_template>
          pipeline_config = {
              "MAX_PROMPT_LEN": {max_prompt_len_value},
              "MIN_RESPONSE_LEN": 512,
              "PREFILL_HINT": "DYNAMIC",
              "GENERATE_HINT": "BEST_PERF",
              "CACHE_DIR": ".npucache",
          }
          pipe = ov_genai.LLMPipeline(model_path, "NPU", pipeline_config)
        </pipeline_config_template>
        <critical_note>
          Each MAX_PROMPT_LEN value requires creating a NEW LLMPipeline instance
          because the static shape is compiled at initialization time.
          Unload/delete the previous pipeline before creating the next one.
          NPU compilation takes time — expect 30-120 seconds per pipeline creation.
          Use CACHE_DIR=".npucache" to speed up subsequent runs.
        </critical_note>
      </test_matrix_npu>

      <test_matrix_gpu_cpu name="Campaign B: GPU and CPU generation">
        <description>
          Test the GPU and CPU for generation workloads. These devices use dynamic shapes
          and do not have the MAX_PROMPT_LEN constraint.
        </description>
        <dimension name="device" values="GPU, CPU" />
        <dimension name="model" values="qwen2.5-1.5b-instruct, qwen3-1.7b" />
        <dimension name="prompt_length_user_tokens" values="128, 256, 512, 1024, 2048, 3072, 4096" />
        <fixed name="output_tokens" value="128" />
        <fixed name="runs_per_point" value="5" note="5 measured runs (2 warmup discarded)" />
        <fixed name="temperature" value="0.0" />
        <model_paths>
          GPU/CPU + qwen2.5: models/qwen2.5-1.5b-instruct/openvino-int4-npu (same weights, OV compiles for target device)
          GPU/CPU + qwen3: models/qwen3-1.7b/openvino-int4 (the generic variant, NOT the npu variant)
        </model_paths>
      </test_matrix_gpu_cpu>

      <per_run_measurements>
        <metric name="ok" type="bool">Did the run complete without error?</metric>
        <metric name="latency_first_token_ms" type="float">Time to first generated token</metric>
        <metric name="latency_total_ms" type="float">Total wall-clock generation time</metric>
        <metric name="tokens_generated" type="int">Number of tokens actually produced</metric>
        <metric name="decode_tokens_per_sec" type="float">Generation throughput</metric>
        <metric name="rss_before_mb" type="float">Process RSS before inference (via psutil)</metric>
        <metric name="rss_peak_mb" type="float">Peak RSS during inference</metric>
        <metric name="rss_after_mb" type="float">Process RSS after inference</metric>
        <metric name="error" type="string_or_null">Error message if failed, null if success</metric>
        <metric name="error_fingerprint" type="string_or_null">Normalized error category</metric>
        <metric name="pipeline_config" type="dict">The pipeline_config used for this run (important for NPU)</metric>
      </per_run_measurements>

      <implementation_guidance>
        <note>Use openvino_genai.LLMPipeline(model_dir, device_name, pipeline_config) for NPU.
              Use openvino_genai.LLMPipeline(model_dir, device_name) for GPU/CPU.</note>
        <note>For NPU: MUST pass pipeline_config with MAX_PROMPT_LEN at pipeline creation time.
              This is the ENTIRE POINT of this milestone — earlier studies never did this.</note>
        <note>For NPU: Each MAX_PROMPT_LEN value requires a fresh pipeline. The static shape
              is compiled at init time and cannot be changed. Delete the old pipeline,
              force garbage collection (gc.collect()), then create the new one.</note>
        <note>For GPU/CPU: No pipeline_config is needed for prompt length (no static shape constraint).
              Optionally pass CACHE_DIR for compilation caching.</note>
        <note>Build prompts using the Qwen2.5 chat template format:
              &lt;|im_start|&gt;system\n{system_prompt}&lt;|im_end|&gt;\n
              &lt;|im_start|&gt;user\n{user_content}&lt;|im_end|&gt;\n
              &lt;|im_start|&gt;assistant\n
              Pad user_content with repeated filler text to reach target token count.
              For Qwen3, read the chat_template.jinja in models/qwen3-1.7b/openvino-int4/
              to determine the correct format.</note>
        <note>Load each device+model+config combination ONCE, then run all prompt lengths on it.
              Unload before loading the next combination to avoid memory stacking.</note>
        <note>Wrap every inference call in try/except. Record the error but continue
              to the next test point. A failure at one prompt length is DATA, not a crash.</note>
        <note>If a pipeline CREATION fails (e.g., out of memory during compilation for
              MAX_PROMPT_LEN=8192), that IS the answer for that config — record it and move on.</note>
        <note>Use generation_config with max_new_tokens=128, temperature=0 (greedy).</note>
        <note>Do NOT test Qwen3 on NPU — it is not Intel-supported for NPU.</note>
      </implementation_guidance>
    </phase>

    <phase number="3" name="Run the Benchmark">
      <step>Run the script on AC power with no other heavy processes</step>
      <step>Script produces: phase2_gates/evidence/p5_multi_device_capability_matrix.json</step>
      <step>Expected runtime: 45-90 minutes
            Campaign A: 6 NPU configs × compilation time + inference runs
            Campaign B: 4 GPU/CPU combos × 7 prompt lengths × 7 runs each</step>
      <step>If a pipeline creation fails (e.g., MAX_PROMPT_LEN=8192 causes OOM during compile),
            record that as a pipeline_creation_error and continue to the next config</step>
    </phase>

    <phase number="4" name="Analysis and Decision Artifacts">
      <step>Produce a summary document: docs/FEASIBILITY_MULTI_DEVICE_CAPABILITY.md</step>

      <summary_document_structure>
        <section name="1. NPU MAX_PROMPT_LEN Scaling Results">
          The most important section. For each MAX_PROMPT_LEN config tested:
          - Did the pipeline compile successfully? How long did compilation take?
          - What prompt lengths succeeded? Failed?
          - Latency at each prompt length (first-token and total)
          - Throughput (tokens/sec) at each prompt length
          - Memory (RSS) at each prompt length
          - CONCLUSION: What is the highest MAX_PROMPT_LEN that works reliably on this NPU?
        </section>

        <section name="2. GPU Generation Results">
          For Qwen2.5 and Qwen3 on GPU:
          - Maximum prompt length that succeeded
          - Latency and throughput at each prompt length
          - Memory usage
          - Comparison to NPU at matching prompt lengths
        </section>

        <section name="3. CPU Generation Results">
          Same structure as GPU section.
        </section>

        <section name="4. Cross-Device Comparison Table">
          At each prompt length, side-by-side comparison of all devices that support it:
          | Prompt Length | NPU (latency/tps) | GPU (latency/tps) | CPU (latency/tps) |
          Show for both Qwen2.5 (all devices) and Qwen3 (GPU/CPU only).
        </section>

        <section name="5. Model Comparison (Qwen2.5 vs Qwen3)">
          On GPU and CPU where both can be tested:
          - Which model is faster?
          - Which uses less memory?
          - Which generates better-quality output? (subjective, but note observations)
        </section>

        <section name="6. Device Allocation Recommendation">
          Based on ALL the data, answer:
          A. What is the TRUE maximum context the NPU can support when properly configured?
          B. How does GPU generation compare to NPU in speed and context length?
          C. Is CPU a viable fallback for very long contexts?
          D. Should the system architecture change? Possible outcomes:
             - EXPAND_ON_NPU: Just raise MAX_PROMPT_LEN in production code. No device change needed.
             - MOVE_TO_GPU: GPU is better for generation overall (faster + longer context)
             - HYBRID_NPU_GPU: NPU for short contexts (fast), GPU for long contexts
             - EXPAND_ON_NPU_UPGRADE_MODEL: Raise MAX_PROMPT_LEN AND switch to Qwen3 on GPU
             - DO_NOT_EXPAND: Even with raised MAX_PROMPT_LEN, performance degrades too much
        </section>

        <section name="7. Disposition">
          One of:
          - EXPAND_ON_NPU: Raise MAX_PROMPT_LEN to [value]. Recommend production code change.
          - EXPAND_ON_[DEVICE]: Context expansion feasible on [device]. Recommend ADR-011.
          - HYBRID_[DEVICE1]_[DEVICE2]: Hybrid approach feasible. Recommend ADR-011.
          - DO_NOT_EXPAND: No viable expansion path with acceptable performance.
          - INSUFFICIENT_EVIDENCE: [explain what blocked evidence collection]
        </section>
      </summary_document_structure>
    </phase>

    <phase number="5" name="Commit and Ledger Update">
      <step>Commit all evidence artifacts and the summary document</step>
      <step>Update docs/POST_OPERATIONAL_MATURATION_LEDGER.md with P5-FEASIBILITY-004 entry</step>
      <step>Update docs/IMPLEMENTATION_PLAN.md if appropriate</step>
      <step>Commit template: "P5-FEASIBILITY-004: multi-device capability matrix [disposition]"</step>
    </phase>

  </execution_plan>

  <quality_gate name="Device Capability Gate (DCG)">
    <description>
      This gate evaluates whether ENOUGH data was collected to make a device
      allocation decision. Failures at high prompt lengths are EXPECTED DATA.
    </description>

    <checks>
      <check id="DCG-01" name="Baseline Validation">
        At least ONE device × model combination must produce ≥5 valid runs
        at prompt length 512 user tokens. If nothing works at 512 tokens,
        the test harness itself is broken.
      </check>
      <check id="DCG-02" name="NPU MAX_PROMPT_LEN Scaling">
        The NPU must be tested with at least 3 different MAX_PROMPT_LEN values
        (including the default 1024 and at least one value ≥2048).
        If MAX_PROMPT_LEN=2048 succeeds at runtime, this invalidates the prior
        "1024 hard wall" conclusion from P5-001/002/003.
      </check>
      <check id="DCG-03" name="GPU Generation Data">
        GPU must be tested for generation (not just classification).
        At least 3 prompt length bands must have valid GPU generation results.
        If GPU fails to LOAD for generation, record as "GPU_GENERATION_NOT_SUPPORTED".
      </check>
      <check id="DCG-04" name="CPU Generation Data">
        CPU must be tested for generation.
        At least 3 prompt length bands must have valid CPU generation results.
        If CPU fails to LOAD, record as "CPU_GENERATION_NOT_SUPPORTED".
      </check>
      <check id="DCG-05" name="Cross-Device Comparison Possible">
        At least ONE prompt length must have valid results from ≥2 devices,
        enabling a direct performance comparison.
      </check>
      <check id="DCG-06" name="Memory Safety">
        No test point caused an out-of-memory crash or system instability.
        If RSS exceeds 28 GB (90% of ceiling), flag but do not fail.
      </check>
      <check id="DCG-07" name="Qwen3 GPU/CPU Tested">
        Qwen3-1.7B must be tested on at least GPU or CPU with at least 1 prompt length.
        If it fails to load on both, record as "QWEN3_NOT_LOADABLE" and note which errors.
      </check>
    </checks>

    <disposition_rules>
      <rule>If DCG-01 through DCG-05 all PASS → disposition is the recommendation from Section 6D of the summary</rule>
      <rule>If DCG-01 FAILS → HARNESS_ERROR, investigate script bugs before re-running</rule>
      <rule>If DCG-02 shows NPU works at MAX_PROMPT_LEN ≥2048 → the prior "1024 wall" is OVERTURNED</rule>
      <rule>If DCG-03 and DCG-04 both FAIL (neither GPU nor CPU loads for generation) AND
            NPU cannot expand beyond 1024 → DO_NOT_EXPAND</rule>
      <rule>If only some checks fail → PARTIAL_EVIDENCE, document what was collected and what was not</rule>
    </disposition_rules>
  </quality_gate>

  <rules>
    <rule>Execute phases sequentially. Do not skip phases.</rule>
    <rule>Record ALL results — failures are data, not errors to hide.</rule>
    <rule>Do not modify any production code (services/, shared/, launcher/).</rule>
    <rule>Do not modify existing evidence files from prior milestones.</rule>
    <rule>AC power enforcement is mandatory. If on battery, stop immediately.</rule>
    <rule>Unload each model before loading the next to prevent memory stacking.</rule>
    <rule>If a model fails to load on a device, skip that combo and continue.</rule>
    <rule>Use greedy decoding (temperature=0) for all runs.</rule>
    <rule>Do NOT test Qwen3 on NPU — it is not supported by Intel.</rule>
    <rule>Commit on branch feature/p5-feasibility-004-multi-device, not main.</rule>
    <rule>Stop after Phase 5. Do not start unrequested work.</rule>
  </rules>

</execution_prompt>
```
