---
title: P5_FEASIBILITY_005a_EAGLE3_PROMPT
status: archived
area: portfolio
---

# P5-FEASIBILITY-005a-EAGLE3 Execution Prompt — EAGLE-3 Draft Head Conversion and Benchmark Gap Fill (14B Only)

Paste the XML block below into a new Execution Agent chat session along with the listed attachments.

---

## Required Attachments

1. `.github/copilot-instructions.md`
2. `phase2_gates/scripts/run_p5_feasibility_005a.py` — benchmark harness
3. `phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json` — current benchmark evidence (T-05 SKIPPED)
4. `shared/constants.py`
5. `docs/adrs/ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md`

---

## Context

P5-005a executed an 18-test benchmark matrix. Test T-05 ("14B + EAGLE-3") was SKIPPED with
reason `DRAFT_MODEL_NOT_AVAILABLE` because the EAGLE-3 draft head was never converted to
OpenVINO IR. This prompt fills that gap for the 14B model only. T-07 (8B + EAGLE-3) is
out of scope — no 8B model is present in this workspace.

**Pre-flight confirmation (verified before this prompt was issued):**

1. The raw EAGLE-3 14B model is **already on disk** at `models/eagle3-qwen3-14b-raw/` —
   `pytorch_model.bin` and `config.json` are present. No HuggingFace download is needed.
2. The raw model has `architectures: ['LlamaForCausalLMEagle3']` and `model_type: llama` —
   it is a candidate for conversion via `OVModelForCausalLM` with `trust_remote_code=True`.
3. Both bugs previously described in the `should_skip_test()` harness function are **already
   fixed** in the current code (eagle check comes first; ternary precedence is correct).
   Phase 1 is verification only — do NOT attempt to rewrite the function.
4. `models/eagle3-qwen3-14b/` (OpenVINO IR destination) is empty — conversion has not run.

**NOTE on deprecated harness API (line \~442 of run_p5_feasibility_005a.py):**
The harness uses the dict-based `LLMPipeline` constructor:
`ov_genai.LLMPipeline(str(model_dir), "GPU", config, **kwargs)`
In OpenVINO GenAI 2026.0 the keyword-based form is preferred. The dict form may still
execute — verify it runs without error before benchmarking. If it raises a `TypeError`,
update to keyword-based form at that line only.

**EAGLE-3 Candidate (14B):**

| Repo | Downloads | Notes |
|------|-----------|-------|
| `AngelSlim/Qwen3-14B_eagle3` | 1,390 | Highest adoption 14B — raw weights already on disk |
| `RedHatAI/Qwen3-14B-speculator.eagle3` | 292 | RedHat official fallback (download only if conversion of existing raw model fails) |

---

## XML Execution Prompt

```xml
<execution_prompt milestone="P5-FEASIBILITY-005a-EAGLE3" type="gap_fill_empirical">

  <context>
    <summary>
      P5-005a completed its main benchmark matrix but SKIPPED T-05 (14B + EAGLE-3) because
      the EAGLE-3 draft head model was never converted to OpenVINO IR. T-07 (8B + EAGLE-3)
      is out of scope — no 8B model is present in this workspace. This follow-on milestone
      converts the existing raw EAGLE-3 14B head (already on disk), verifies it loads in
      the OpenVINO GenAI LLMPipeline, and re-runs ONLY T-05 to fill the gap in the evidence
      matrix. Harness bugs previously noted are already fixed — Phase 1 is verification only.
    </summary>

    <prior_evidence milestone="P5-005a">
      <status>18-test matrix partially complete. T-05 SKIPPED (EAGLE-3 not available)
        — all other completed tests remain unchanged.</status>
      <evidence_artifact>phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json</evidence_artifact>
      <eagle3_state>
        Raw EAGLE-3 14B weights are on disk at models/eagle3-qwen3-14b-raw/.
        architectures: ['LlamaForCausalLMEagle3'], model_type: llama.
        models/eagle3-qwen3-14b/ exists but is EMPTY — conversion has not run.
      </eagle3_state>
    </prior_evidence>

    <hardware_and_environment>
      <soc>Intel Core Ultra 7 258V (Lunar Lake)</soc>
      <gpu>Arc 140V (Xe2) — ALL LLM inference on GPU per ADR-011</gpu>
      <memory>31,323 MB effective ceiling (ADR-005). ~15,507 MB available for LLM agents.</memory>
      <python>C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe (Python 3.11.9)</python>
      <openvino>2026.0.0 / GenAI 2026.0.0.0</openvino>
      <workspace>C:\Users\mrbla\BlarAI</workspace>
      <branch>Create new branch feature/p5-005a-eagle3-gap-fill from main before any changes.</branch>
    </hardware_and_environment>

    <eagle3_background>
      EAGLE-3 is a speculative decoding technique that uses a lightweight draft head
      (trained on the target model's hidden states) to predict multiple future tokens
      in parallel. Unlike standard assisted generation which uses a separate smaller
      model as the drafter, EAGLE-3 heads are architecturally coupled to their specific
      target model.

      KEY IMPLICATIONS FOR THIS TASK:
      1. EAGLE-3 heads are NOT standalone models — the eagle3-qwen3-14b head only works
         with Qwen3-14B. The head and target model must be used together.
      2. OpenVINO GenAI's LLMPipeline may or may not support EAGLE-3 tree-structured
         speculative decoding. This is a FEASIBILITY question — FRAMEWORK_NOT_SUPPORTED
         is a valid outcome, not a failure.
      3. The raw EAGLE-3 14B head (`models/eagle3-qwen3-14b-raw/`) has
         `architectures: ['LlamaForCausalLMEagle3']` and `model_type: llama`.
         Conversion should attempt `OVModelForCausalLM.from_pretrained()` with
         `trust_remote_code=True` as the primary path. If that fails, record the
         exact error and attempt ONNX export as a fallback before declaring failure.
      4. EAGLE-3 heads are very small (~100-300 MB) — disk/memory is not a concern.
    </eagle3_background>

    <model_paths>
      <target_14b>models/qwen3-14b/openvino-int4-gpu/</target_14b>
      <eagle3_14b_raw>models/eagle3-qwen3-14b-raw/</eagle3_14b_raw>
      <eagle3_14b_destination>models/eagle3-qwen3-14b/</eagle3_14b_destination>
    </model_paths>

    <candidate_repos>
      <eagle3_14b>
        <note>Raw weights from AngelSlim/Qwen3-14B_eagle3 are already on disk at
          models/eagle3-qwen3-14b-raw/. Do NOT re-download unless conversion fails
          AND the fallback repo has a different architecture that may succeed.</note>
        <primary repo="AngelSlim/Qwen3-14B_eagle3" downloads="1390"
          rationale="Highest adoption 14B candidate — raw model already on disk." />
        <fallback repo="RedHatAI/Qwen3-14B-speculator.eagle3" downloads="292"
          rationale="RedHat official fallback — download ONLY if conversion of existing raw model fails with all approaches." />
      </eagle3_14b>
    </candidate_repos>
  </context>

  <objective>
    1. Verify the harness `should_skip_test()` eagle logic is correct (already fixed —
       confirm only, do not modify).
    2. Verify the harness LLMPipeline API call at line ~442 executes without error in
       GenAI 2026.0; if it raises a TypeError, update that line to keyword-based form.
    3. Convert the raw EAGLE-3 14B head (`models/eagle3-qwen3-14b-raw/`) to OpenVINO IR
       at `models/eagle3-qwen3-14b/`.
    4. Validate the converted head loads in an `ov_genai.LLMPipeline` with the 14B target.
    5. Re-run ONLY test T-05 using the benchmark harness's measurement parameters
       (same prompt bands, warmup runs, measured runs, max_new_tokens as the main study).
    6. Merge the T-05 result into the existing evidence matrix JSON.
    7. If EAGLE-3 is not supported by the OpenVINO GenAI pipeline, record the specific
       error and set disposition to FRAMEWORK_NOT_SUPPORTED — this is a valid outcome.
  </objective>

  <non_goals>
    <item>Do NOT re-run any test other than T-05.</item>
    <item>Do NOT acquire, convert, or benchmark any 8B EAGLE-3 model — no 8B model
      exists in this workspace.</item>
    <item>Do NOT modify the benchmark parameters (prompt bands, run counts, etc.).</item>
    <item>Do NOT delete or overwrite the existing evidence matrix — MERGE T-05 in.</item>
    <item>Do NOT rewrite should_skip_test() — the bug fix is already in place. Only
      verify it is correct.</item>
    <item>Do NOT train or fine-tune EAGLE-3 heads — use pre-trained weights only.</item>
    <item>This is NOT an Architectural Decision Gate — EAGLE-3 is an enhancement path
      within the already-accepted speculative decoding investigation.</item>
  </non_goals>

  <locked_architecture>
    <adr name="ADR-011">All LLM inference on GPU. NPU retired from P1 Core Loop.
      EAGLE-3 draft heads run on GPU alongside their target model.</adr>
    <adr name="ADR-005">31,323 MB memory ceiling. Monitor RSS during EAGLE-3 tests —
      EAGLE-3 heads are small but the target model is large (14B ~9.5 GB RSS).</adr>
    <context_window>4,096 token hard-cap. DO NOT EXPAND.</context_window>
    <privacy>HuggingFace download authorized during acquisition phase ONLY.
      No network calls during benchmarking.</privacy>
    <power>Must run on AC power during benchmarking.</power>
  </locked_architecture>

  <execution_plan>

    <phase number="0" name="Pre-Flight and State Assessment">
      <step>Confirm git branch: create and check out `feature/p5-005a-eagle3-gap-fill`
        from `main` before making any file changes.</step>
      <step>Read the current evidence matrix and confirm T-05 status=skipped.</step>
      <step>Verify target model exists:
        - models/qwen3-14b/openvino-int4-gpu/openvino_model.xml
        - models/qwen3-14b/openvino-int4-gpu/openvino_model.bin</step>
      <step>Verify raw EAGLE-3 head on disk:
        - models/eagle3-qwen3-14b-raw/pytorch_model.bin (or model.safetensors)
        - models/eagle3-qwen3-14b-raw/config.json</step>
      <step>Confirm models/eagle3-qwen3-14b/ is empty (no openvino_model.xml present).</step>
      <step>Check AC power status.</step>
      <step>Check disk space (need ~2 GB free for conversion working set).</step>
    </phase>

    <phase number="1" name="Harness Verification">
      <description>
        Both harness bugs previously described are already fixed. This phase verifies
        the current state only — do NOT modify the harness unless the compile or
        pipeline smoke test fails.
      </description>
      <step>Syntax-check the harness:
        `python -m py_compile phase2_gates/scripts/run_p5_feasibility_005a.py`
        Expected output: no errors.</step>
      <step>Confirm `should_skip_test()` eagle logic by reading the function:
        the `if test.get("eagle"):` block must appear BEFORE the generic
        `if test.get("draft_model_path") is not None:` block. If it does not,
        apply the corrected ordering documented in the context. If it already does,
        record "eagle_check_order: VERIFIED" and proceed.</step>
      <step>Locate the LLMPipeline constructor call at line ~442 of the harness.
        Run a quick import smoke test to verify no TypeError is raised:
        ```python
        import openvino_genai as ov_genai
        import json
        sc = ov_genai.SchedulerConfig()
        cfg = {"scheduler_config": sc}
        # If this import succeeds without error, dict-based API is still functional.
        print("GenAI import OK")
        ```
        If the dict-based constructor raises at runtime during benchmarking, update
        ONLY that line to the keyword-based form. Document any change made.</step>
    </phase>

    <phase number="2" name="Raw Model Inspection">
      <description>
        The raw EAGLE-3 14B model is already on disk. No download is needed unless
        conversion fails AND the fallback repo has a different architecture.
      </description>
      <step>Read models/eagle3-qwen3-14b-raw/config.json and record:
        - architectures value
        - model_type value
        - Any custom class definitions (e.g., auto_map entries)
        - Weight files present (pytorch_model.bin vs model.safetensors)
        - Presence or absence of tokenizer files</step>
      <step>Record findings in: phase2_gates/evidence/p5_005a_eagle3_acquisition.json
        Include:
        - source_repo: "AngelSlim/Qwen3-14B_eagle3" (pre-downloaded)
        - architectures, model_type from config.json
        - file listing with sizes (Get-ChildItem models/eagle3-qwen3-14b-raw/)
        - notes on custom code dependencies
      </step>
      <step>IF and ONLY IF the initial conversion in Phase 3 fails with all approaches
        AND the fallback repo (RedHatAI/Qwen3-14B-speculator.eagle3) offers a different
        architecture: download the fallback to a temporary directory and retry.
        Network access is authorized for this fallback scenario ONLY.</step>
    </phase>

    <phase number="3" name="OpenVINO Conversion">
      <description>
        Convert the raw EAGLE-3 14B head to OpenVINO IR format.
        The raw model has architectures=['LlamaForCausalLMEagle3'] and model_type='llama'.
        This is a standard-derived architecture — attempt OVModelForCausalLM first.
      </description>

      <step>Primary conversion path — OVModelForCausalLM with trust_remote_code:
        ```python
        from optimum.intel import OVModelForCausalLM
        model = OVModelForCausalLM.from_pretrained(
            "models/eagle3-qwen3-14b-raw",
            export=True,
            trust_remote_code=True,
            weight_format="int4_sym_g128",
        )
        model.save_pretrained("models/eagle3-qwen3-14b")
        ```
        Verify that `models/eagle3-qwen3-14b/openvino_model.xml` and
        `models/eagle3-qwen3-14b/openvino_model.bin` are produced.</step>

      <step>If the primary path fails (unsupported architecture, missing custom class,
        etc.), record the exact exception and attempt ONNX export as a secondary path:
        ```python
        from transformers import AutoModelForCausalLM
        import torch
        model = AutoModelForCausalLM.from_pretrained(
            "models/eagle3-qwen3-14b-raw", trust_remote_code=True
        )
        torch.onnx.export(model, ...)
        # Then convert ONNX -> OpenVINO IR via openvino.convert_model
        ```
        If ONNX export also fails, record the error, declare
        EAGLE3_NOT_CONVERTIBLE, and stop. Do NOT attempt further workarounds.
      </step>

      <step>Validate the converted model loads in LLMPipeline with the 14B target:
        ```python
        import openvino_genai as ov_genai
        pipe = ov_genai.LLMPipeline(
            str(Path("models/qwen3-14b/openvino-int4-gpu")),
            device="GPU",
            draft_model=ov_genai.draft_model(
                str(Path("models/eagle3-qwen3-14b")), "GPU"
            )
        )
        del pipe  # release memory before benchmarking
        ```
        If this raises an unsupported-architecture error, record the exact message
        and set disposition to FRAMEWORK_NOT_SUPPORTED. This is a valid outcome —
        do NOT fabricate data or attempt workarounds.</step>
    </phase>

    <phase number="4" name="Benchmark T-05">
      <description>
        Re-run ONLY test T-05 using the same harness parameters.
        Network access is NOT authorized for this phase.
      </description>

      <step>Create a focused runner: phase2_gates/scripts/run_eagle3_gap_fill.py
        Import the benchmark measurement functions from run_p5_feasibility_005a.py
        and run ONLY T-05 with identical parameters. Do NOT modify the main harness
        to add a --tests filter argument (keep harness changes minimal).</step>

      <step>Run T-05 (14B + EAGLE-3) with:
        - Same prompt bands: [128, 256, 512, 1024, 2048, 3072, 4096]
        - Warmup runs: 2
        - Measured runs: 5
        - Max new tokens: 128
        - Device: GPU
        - Record: decode_tokens_per_sec, latency_first_token_ms, latency_total_ms,
          tokens_generated, rss_before_mb, rss_peak_mb, rss_after_mb per run
      </step>

      <step>Compare T-05 to baseline:
        - T-05 vs T-01 (14B baseline) — compute speedup_vs_baseline_512
      </step>
    </phase>

    <phase number="5" name="Evidence Merge and Artifact Production">
      <step>Read the existing p5_005a_unified_draft_feasibility_matrix.json.</step>
      <step>Replace the T-05 entry (status=skipped) with the new completed result.
        Preserve ALL other test entries unchanged.</step>
      <step>Recalculate quality_gate checks if applicable.</step>
      <step>Write the updated matrix back to:
        phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json</step>
      <step>Also produce:
        phase2_gates/evidence/p5_005a_eagle3_acquisition.json (from Phase 2)
        phase2_gates/evidence/p5_005a_eagle3_benchmark.json (standalone T-05 results
          as a separate artifact for audit trail, in addition to the merged matrix)</step>
    </phase>

  </execution_plan>

  <harness_constraint>NO_FULL_HARNESS</harness_constraint>
  <harness_note>
    The main benchmark harness runs the full 18-test matrix. Partial re-run capability
    does not exist — it must be created (Phase 4). The Execution Agent must create a
    focused runner that reuses the harness's measurement functions but executes only T-05.
  </harness_note>

  <evidence_quality_gate>
    <minimum_runs>5 measured runs per prompt band per test (matches main study)</minimum_runs>
    <warmup_runs>2 warmup runs before measurement (matches main study)</warmup_runs>
    <prompt_bands>[128, 256, 512, 1024, 2048, 3072, 4096]</prompt_bands>
    <max_new_tokens>128</max_new_tokens>
    <reproducibility>All 5 measured runs must complete without error (valid_count=5).</reproducibility>
    <rss_ceiling>RSS must not exceed 15,507 MB. If a test exceeds this, it is VALID data
      but flagged as OVER_BUDGET.</rss_ceiling>
    <disposition_if_framework_unsupported>
      If OpenVINO GenAI does not support EAGLE-3 speculative decoding:
      disposition = FRAMEWORK_NOT_SUPPORTED.
      This is a valid outcome — record the specific error message and pipeline version.
      Do NOT fabricate data or attempt workarounds.
    </disposition_if_framework_unsupported>
    <disposition_if_conversion_fails>
      If the raw model cannot be converted via any path:
      disposition = EAGLE3_NOT_CONVERTIBLE.
      Record the exact failure for each approach attempted.
    </disposition_if_conversion_fails>
    <disposition_if_successful>
      If T-05 completes with valid_count=5 across all prompt bands:
      disposition = EAGLE3_GAP_FILLED.
      Merge into matrix and report speedup vs T-01 baseline.
    </disposition_if_successful>
  </evidence_quality_gate>

  <documentation_updates_mandatory>
    <item>Update phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json
      with T-05 result (or updated skip reason if not achievable).</item>
    <item>Do NOT update docs/IMPLEMENTATION_PLAN.md or docs/POST_OPERATIONAL_MATURATION_LEDGER.md —
      this is a sub-milestone within P5-005a, not a standalone ledger entry.</item>
  </documentation_updates_mandatory>

  <test_and_validation_targets>
    <compile>python -m py_compile phase2_gates/scripts/run_p5_feasibility_005a.py</compile>
    <test>python -m pytest tests/ -x -q (verify no regressions after any harness touch)</test>
    <benchmark>Run focused T-05 script — observe all 5 measured runs per prompt band</benchmark>
  </test_and_validation_targets>

  <deliverables>
    <item>phase2_gates/scripts/run_eagle3_gap_fill.py — focused T-05 runner</item>
    <item>phase2_gates/evidence/p5_005a_eagle3_acquisition.json — raw model inspection evidence</item>
    <item>phase2_gates/evidence/p5_005a_eagle3_benchmark.json — standalone T-05 benchmark evidence</item>
    <item>phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json — updated with T-05 result merged in</item>
    <item>models/eagle3-qwen3-14b/ — converted EAGLE-3 head for 14B (if convertible)</item>
  </deliverables>

  <commit_template>
    P5-005a EAGLE-3 gap fill: T-05 {disposition}

    - Raw model: models/eagle3-qwen3-14b-raw/ (AngelSlim/Qwen3-14B_eagle3)
    - Converted to OpenVINO IR: {success/failure details}
    - T-05 result: {tps_512 or FRAMEWORK_NOT_SUPPORTED or EAGLE3_NOT_CONVERTIBLE}
    - Evidence: p5_005a_eagle3_acquisition.json, p5_005a_eagle3_benchmark.json
    - Matrix updated: p5_005a_unified_draft_feasibility_matrix.json
  </commit_template>

  <role_boundary>
    You are an Execution Agent. Execute this milestone ONLY. Do NOT generate SDO prompts,
    continuation prompts, or planning documents. If scope is insufficient, fail closed
    and state what is missing.
  </role_boundary>

</execution_prompt>
```
