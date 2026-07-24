---
title: P5_FEASIBILITY_005a_FULL_RERUN_PROMPT
status: archived
area: portfolio
---

# P5-FEASIBILITY-005a — Full Rerun with EAGLE-3 Acquisition

Paste the XML block below into a **new Execution Agent chat session** along with the listed
attachments. This prompt restarts the ENTIRE P5-005a benchmark from scratch, including
EAGLE-3 model acquisition and all harness bug fixes, in a single autonomous run.

**Pre-requisites before starting this session:**
1. Reboot completed (PlatformAoAcOverride=0 registry fix now active — S0 Low Power Idle disabled).
2. AC power connected.
3. No other Python processes running (especially no prior benchmark PIDs).
4. YouTube or other GPU-consuming applications CLOSED (they contaminate TPS measurements).

---

## Required Attachments

1. `.github/copilot-instructions.md`
2. `phase2_gates/scripts/run_p5_feasibility_005a.py` — benchmark harness (contains 3 bugs to fix)
3. `phase2_gates/scripts/acquire_p5_005a_models.py` — acquisition script (reference for patterns)
4. `phase2_gates/evidence/p5_005a_model_acquisition.json` — acquisition evidence (contains eagle3_investigation)
5. `phase2_gates/evidence/p5_005a_cross_device_draft_discovery.json` — cross-device discovery evidence
6. `shared/constants.py`
7. `docs/adrs/ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md`

**DO NOT ATTACH** `p5_005a_unified_draft_feasibility_matrix.json` — the harness will generate
a fresh one. The current file is empty (0 tests — wiped by a prior crashed run).

---

## Why This Prompt Exists

The P5-005a feasibility study has been run **three times today**, all three failed:
- **Run 1:** Process crashed (exit code 1).
- **Run 2:** Completed T-01 through T-09, then Windows Modern Standby (S0 Low Power Idle)
  put the system to sleep and killed the process. All data lost (harness has no resume).
- **Run 3:** Restarted from scratch, wiped evidence, killed by user after T-01 when it
  became clear the YouTube keepawake workaround was contaminating GPU measurements (36% TPS
  degradation from GPU resource contention).

The root cause (Modern Standby on Lunar Lake, no S3 available) has been addressed:
`PlatformAoAcOverride=0` was written to `HKLM:\SYSTEM\CurrentControlSet\Control\Power` and
the system has been **rebooted** to activate it. `powercfg /a` should no longer show
"S0 Low Power Idle" as an available sleep state.

Additionally, T-05 and T-07 (EAGLE-3 tests) were always going to be SKIPPED because the
acquisition script was investigate-only and the harness has bugs in `should_skip_test()`.
This prompt fixes those bugs and adds EAGLE-3 acquisition so ALL 18 tests can execute.

---

## XML Execution Prompt

```xml
<execution_prompt milestone="P5-FEASIBILITY-005a-FULL-RERUN" type="full_empirical_with_eagle3">

  <context>
    <summary>
      Complete restart of the P5-005a feasibility study. This prompt:
      1. Verifies the Modern Standby fix is active (mandatory pre-gate).
      2. Fixes 3 bugs in the benchmark harness should_skip_test() function.
      3. Acquires EAGLE-3 draft head models from HuggingFace and converts to OpenVINO IR.
      4. Runs the FULL 18-test benchmark matrix from T-01 through T-18.
      5. Evaluates quality gates and produces the final evidence artifact.
      
      This is a CLEAN start — the evidence file will be generated fresh by the harness.
      No prior run data exists (all was lost to crashes and Modern Standby kills).
    </summary>

    <prior_attempts>
      <run number="1" status="CRASHED" cause="Process exit code 1" data_lost="YES" />
      <run number="2" status="KILLED_BY_STANDBY" cause="S0 Low Power Idle at 15:30"
        progress="T-01 through T-09 completed" data_lost="YES" />
      <run number="3" status="KILLED_BY_USER" cause="YouTube GPU contamination detected"
        progress="T-01 only" data_lost="YES" />
      <modern_standby_fix>
        Registry: PlatformAoAcOverride=0 at HKLM:\SYSTEM\CurrentControlSet\Control\Power
        Status: SET and REBOOT COMPLETED. S0 Low Power Idle should now be disabled.
      </modern_standby_fix>
    </prior_attempts>

    <hardware_and_environment>
      <soc>Intel Core Ultra 7 258V (Lunar Lake)</soc>
      <gpu>Arc 140V (Xe2) — ALL LLM inference on GPU per ADR-011</gpu>
      <memory>31,323 MB effective ceiling (ADR-005). ~15,507 MB available for LLM agents.</memory>
      <python>C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe (Python 3.11.9)</python>
      <openvino>2026.0.0 / GenAI 2026.0.0.0</openvino>
      <workspace>C:\Users\mrbla\BlarAI</workspace>
      <branch>feature/p5-feasibility-005-unified-model</branch>
    </hardware_and_environment>

    <eagle3_background>
      EAGLE-3 is a speculative decoding technique using a lightweight draft head trained
      on the target model's hidden states to predict multiple tokens in parallel. Unlike
      standard assisted generation (which uses a separate smaller model), EAGLE-3 heads
      are architecturally coupled to their specific target model.

      KEY IMPLICATIONS:
      1. EAGLE-3 heads are NOT standalone models — "eagle3-qwen3-8b" only works with Qwen3-8B.
      2. OpenVINO GenAI's LLMPipeline may or may not support EAGLE-3 tree-structured
         speculative decoding. If unsupported, disposition is FRAMEWORK_NOT_SUPPORTED (valid).
      3. HuggingFace EAGLE-3 repos contain PyTorch/SafeTensors weights needing OpenVINO conversion.
      4. EAGLE-3 heads are very small (~100-300 MB) — disk/memory is not a concern.
    </eagle3_background>

    <model_paths>
      <target_14b>models/qwen3-14b/openvino-int4-gpu/</target_14b>
      <target_8b>models/qwen3-8b/openvino-int4-gpu/</target_8b>
      <draft_06b_gpu>models/qwen3-0.6b/openvino-int4-gpu/</draft_06b_gpu>
      <draft_17b_gpu>models/qwen3-1.7b/openvino-int4/</draft_17b_gpu>
      <draft_06b_npu>models/qwen3-0.6b/openvino-int4-npu/</draft_06b_npu>
      <draft_17b_npu>models/qwen3-1.7b/openvino-int4-npu/</draft_17b_npu>
      <eagle3_14b_destination>models/eagle3-qwen3-14b/</eagle3_14b_destination>
      <eagle3_8b_destination>models/eagle3-qwen3-8b/</eagle3_8b_destination>
      <note>All base models are already acquired and validated. Only EAGLE-3 dirs are missing.</note>
    </model_paths>

    <candidate_repos>
      <eagle3_8b>
        <primary repo="RedHatAI/Qwen3-8B-speculator.eagle3" downloads="70873"
          rationale="Highest adoption, official RedHat release. Try this first." />
        <fallback repo="AngelSlim/Qwen3-8B_eagle3" downloads="12319"
          rationale="High-adoption community alternative if RedHat format incompatible." />
      </eagle3_8b>
      <eagle3_14b>
        <primary repo="AngelSlim/Qwen3-14B_eagle3" downloads="1390"
          rationale="Highest adoption 14B candidate." />
        <fallback repo="RedHatAI/Qwen3-14B-speculator.eagle3" downloads="292"
          rationale="RedHat official if AngelSlim format incompatible." />
      </eagle3_14b>
    </candidate_repos>

    <known_bugs count="3">
      <bug id="1" name="Eagle check ordering" location="should_skip_test() ~line 479-483">
        The generic `draft_model_path` check catches EAGLE tests with DRAFT_MODEL_NOT_AVAILABLE
        before the eagle-specific check is reached. The eagle check MUST come FIRST.
      </bug>
      <bug id="2" name="Ternary precedence" location="should_skip_test() ~line 485">
        `return True, "EAGLE3_DRAFT_NOT_AVAILABLE" if not path_has_model(...) else (False, None)`
        Due to Python operator precedence, when model IS present this returns `True, (False, None)`
        instead of `(False, None)`. Needs parentheses around the full expression.
      </bug>
      <bug id="3" name="Unconditional cross-device abort" location="should_skip_test() ~line 493-494">
        `if test.get("cross_device"): return True, "CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT"`
        This unconditionally skips ALL cross-device tests (T-13 through T-16) regardless of whether
        NPU discovery says they are supported. This was likely added after a fatal NPU crash.
        
        DISPOSITION FOR THIS BUG: LEAVE IT AS-IS. ADR-011 retired NPU from the P1 Core Loop.
        Cross-device NPU tests are informational only. The unconditional skip is a safety guard
        against fatal NPU compiler aborts that were observed during development. The cross-device
        discovery evidence already captured that NPU cross-device IS supported (latency 23s),
        so the discovery data is preserved even though T-13–T-16 will be skipped.
        
        DO NOT remove the CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT guard.
      </bug>
    </known_bugs>
  </context>

  <objective>
    Execute the following phases IN ORDER. The entire execution must be autonomous —
    the Lead Architect will not be present. If any phase fails, record the failure,
    assess whether subsequent phases can still proceed, and continue where possible
    (fail-open for acquisition, fail-closed for data integrity).
    
    1. Verify Modern Standby fix is active (mandatory gate — abort if not).
    2. Fix the 3 bugs in the benchmark harness should_skip_test().
    3. Acquire EAGLE-3 draft head models from HuggingFace.
    4. Convert EAGLE-3 models to OpenVINO IR format.
    5. Run the FULL 18-test benchmark matrix (T-01 through T-18).
    6. Evaluate quality gates.
    7. Commit all changes.
    
    CRITICAL: If EAGLE-3 acquisition or conversion FAILS, the benchmark MUST STILL RUN.
    The harness will correctly skip T-05/T-07 with the appropriate reason code. The other
    16 tests are independent and must execute regardless.
  </objective>

  <non_goals>
    <item>Do NOT attempt to resume from prior run data — all prior data is LOST.</item>
    <item>Do NOT modify benchmark parameters (prompt bands, run counts, max_new_tokens, etc.).</item>
    <item>Do NOT remove the CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT guard.</item>
    <item>Do NOT train or fine-tune EAGLE-3 heads — acquire pre-trained only.</item>
    <item>Do NOT run YouTube, browsers, or other GPU-consuming processes during benchmarking.</item>
    <item>Do NOT attempt to add resume logic to the harness — that is a future enhancement.</item>
    <item>This is NOT an Architectural Decision Gate.</item>
  </non_goals>

  <locked_architecture>
    <adr name="ADR-011">All LLM inference on GPU. NPU retired from P1 Core Loop.
      EAGLE-3 draft heads run on GPU alongside their target model.</adr>
    <adr name="ADR-005">31,323 MB memory ceiling. Monitor RSS during all tests.</adr>
    <context_window>4,096 token hard-cap. DO NOT EXPAND.</context_window>
    <privacy>HuggingFace download authorized during EAGLE-3 acquisition phase ONLY.
      No network calls during benchmarking.</privacy>
    <power>Must run on AC power during benchmarking.</power>
  </locked_architecture>

  <execution_plan>

    <phase number="0" name="Pre-Flight Verification">
      <description>Mandatory gates that must pass before ANY other work begins.</description>

      <step name="0.1 Modern Standby Verification">
        Run: `powercfg /a`
        VERIFY that "S0 Low Power Idle" is NOT listed as an available sleep state.
        If it IS still listed, the reboot did not activate the fix. In that case:
        1. Verify the registry value exists:
           `Get-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Control\Power" -Name PlatformAoAcOverride`
           It should show Value=0.
        2. If the value exists but S0 is still available: ABORT. The fix may require a
           different approach on Lunar Lake. Record the powercfg output and stop.
        3. If the value does NOT exist: re-create it and inform the user a reboot is needed.
      </step>

      <step name="0.2 Process Deconfliction">
        Run: `Get-Process python* | Select-Object Id, ProcessName, StartTime, WorkingSet64`
        If ANY Python processes are running that match benchmark or acquisition scripts, ABORT.
        Prior runs must be fully dead. Kill any stragglers if found.
      </step>

      <step name="0.3 AC Power Verification">
        The harness enforces this automatically (enforce_ac_power_or_fail_closed), but
        confirm it here too for early abort.
      </step>

      <step name="0.4 GPU Resource Verification">
        Verify no other GPU-intensive processes are running that would contaminate measurements.
        Check for browser processes, streaming applications, etc. Close them if found.
      </step>

      <step name="0.5 Disk Space">
        Verify at least 5 GB free on C:\ (EAGLE-3 heads + conversion working set + evidence).
      </step>

      <step name="0.6 Model Availability">
        Verify ALL base models exist and have openvino_model.xml + openvino_model.bin:
        - models/qwen3-14b/openvino-int4-gpu/
        - models/qwen3-8b/openvino-int4-gpu/
        - models/qwen3-0.6b/openvino-int4-gpu/
        - models/qwen3-1.7b/openvino-int4/
        - models/qwen3-0.6b/openvino-int4-npu/
        - models/qwen3-1.7b/openvino-int4-npu/
        These were all validated in prior runs and should still be present.
      </step>

      <step name="0.7 Git State">
        Confirm on branch `feature/p5-feasibility-005-unified-model`.
        Check for uncommitted changes — commit or stash if needed.
      </step>
    </phase>

    <phase number="1" name="Fix Benchmark Harness Bugs">
      <description>
        Fix bugs 1 and 2 in should_skip_test(). Bug 3 is left as-is (see known_bugs above).
        This must be done BEFORE any benchmark execution.
      </description>

      <step name="1.1 Restructure should_skip_test()">
        In `phase2_gates/scripts/run_p5_feasibility_005a.py`, restructure should_skip_test()
        so that the EAGLE-3 check comes BEFORE the generic draft_model_path check, and fix
        the ternary precedence. The corrected section should read:

        ```python
        # --- EAGLE-3 specific check (MUST come before generic draft check) ---
        if test.get("eagle"):
            if not path_has_model(Path(test["draft_model_path"])):
                return True, "EAGLE3_DRAFT_NOT_AVAILABLE"
            return False, None

        # --- Generic speculative decoding draft model checks ---
        if test.get("draft_model_path") is not None:
            if not bool(capabilities.get("draft_model_api_present")):
                return True, "DRAFT_MODEL_API_NOT_AVAILABLE"
            if not bool(capabilities.get("assistant_gen_fields_present")):
                return True, "ASSISTED_FIELDS_NOT_AVAILABLE"
            if not path_has_model(Path(test["draft_model_path"])):
                return True, "DRAFT_MODEL_NOT_AVAILABLE"
        ```

        LEAVE the cross-device abort guard (bug 3) UNCHANGED:
        ```python
        if test.get("cross_device"):
            return True, "CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT"
        ```
      </step>

      <step name="1.2 Validate Fix">
        Run:
        ```
        python -m py_compile phase2_gates\scripts\run_p5_feasibility_005a.py
        python -m pytest tests\ -x -q
        ```
        Both must pass. If tests fail, diagnose and fix before proceeding.
      </step>
    </phase>

    <phase number="2" name="EAGLE-3 Model Acquisition">
      <description>
        Download EAGLE-3 draft head weights from HuggingFace. Network access is
        authorized for this phase ONLY. If acquisition fails for both candidates,
        record the failure and PROCEED to Phase 4 (the harness will correctly skip
        T-05/T-07 with EAGLE3_DRAFT_NOT_AVAILABLE).
      </description>

      <step name="2.1 Create Acquisition Script">
        Create: `phase2_gates/scripts/acquire_eagle3_models.py`

        The script should:
        1. Download the primary candidate for each target size using huggingface_hub.snapshot_download().
        2. Inspect the downloaded model structure (list files, check config.json, check model
           architecture class, check weight format — safetensors vs pytorch_model.bin).
        3. Record acquisition evidence (repo, commit hash, file sizes, architecture info).
        4. If the primary candidate fails, try the fallback candidate.
        5. Save evidence to: `phase2_gates/evidence/p5_005a_eagle3_acquisition.json`

        Acquisition order:
        - 8B: Try RedHatAI/Qwen3-8B-speculator.eagle3 first → fallback AngelSlim/Qwen3-8B_eagle3
        - 14B: Try AngelSlim/Qwen3-14B_eagle3 first → fallback RedHatAI/Qwen3-14B-speculator.eagle3

        Download locations (temporary, pre-conversion):
        - 8B: models/eagle3-qwen3-8b-raw/
        - 14B: models/eagle3-qwen3-14b-raw/
      </step>

      <step name="2.2 Run Acquisition">
        Execute the acquisition script. Monitor for download failures, network errors,
        or disk space issues. The script must be fail-closed — record exact errors.
      </step>
    </phase>

    <phase number="3" name="EAGLE-3 OpenVINO Conversion">
      <description>
        Convert downloaded EAGLE-3 heads to OpenVINO IR format. If conversion fails
        for ALL candidates, record the failure and PROCEED to Phase 4.
      </description>

      <step name="3.1 Determine Conversion Approach">
        Inspect the downloaded EAGLE-3 model structure:
        - If it has a standard `config.json` with `model_type` recognized by optimum-intel:
          Use `OVModelForCausalLM.from_pretrained()` or optimum-cli export.
        - If it is a non-standard EAGLE-3 architecture (custom head layers):
          Check if OpenVINO GenAI natively loads EAGLE-3 from SafeTensors (some versions do).
          Try: `ov_genai.draft_model(str(raw_path), "GPU")` directly.
        - If completely unsupported: record FRAMEWORK_NOT_SUPPORTED disposition for EAGLE-3.

        IMPORTANT: EAGLE-3 "speculator" models from RedHatAI may use a custom architecture
        that is NOT a standard CausalLM. Inspect config.json carefully — look for
        `architectures`, `model_type`, and any EAGLE-specific fields.
      </step>

      <step name="3.2 Convert and Validate">
        Convert to final destinations:
        - 8B EAGLE-3 → models/eagle3-qwen3-8b/ (must contain openvino_model.xml + .bin)
        - 14B EAGLE-3 → models/eagle3-qwen3-14b/ (must contain openvino_model.xml + .bin)

        Validate that the converted models can be loaded:
        ```python
        import openvino_genai as ov_genai
        # Quick validation — does the pipeline accept the draft model?
        pipe = ov_genai.LLMPipeline(
            str(target_model_path), "GPU",
            {"draft_model": ov_genai.draft_model(str(eagle3_path), "GPU")}
        )
        ```
        If this fails with an architecture error, try the fallback candidate repo.
        If both fail, record the exact error and proceed — T-05/T-07 will be skipped.
      </step>

      <step name="3.3 EAGLE-3 Evidence">
        Record all findings in: `phase2_gates/evidence/p5_005a_eagle3_acquisition.json`
        Include: repos attempted, download success/failure, model structure inspection,
        conversion method used, validation results, file listings with sizes.
      </step>
    </phase>

    <phase number="4" name="Full 18-Test Benchmark">
      <description>
        Run the complete benchmark matrix. This is the primary deliverable.
        Network access is NOT authorized for this phase.
        
        ESTIMATED DURATION: 3-5 hours based on prior run data:
        - Run 2 reached T-09 in ~2 hours (6 completed + 2 skipped + T-09 in progress)
        - T-01 (14B baseline) takes ~15-20 min per prompt band × 7 bands ≈ 2+ hours alone
        - T-06 (8B baseline) is faster — ~8-10 tps
        - Speculative decoding tests add pipeline creation overhead
        
        The Lead Architect will not be present. The process must run unattended.
      </description>

      <step name="4.1 Final Pre-Benchmark Check">
        Before invoking the harness:
        - Confirm no GPU-intensive processes are running.
        - Confirm AC power is connected.
        - Confirm the bug fixes from Phase 1 are in place.
        - Confirm EAGLE-3 model status (present or absent — both are acceptable).
      </step>

      <step name="4.2 Run the Benchmark">
        Execute:
        ```
        cd C:\Users\mrbla\BlarAI
        .venv\Scripts\python.exe phase2_gates\scripts\run_p5_feasibility_005a.py
        ```
        
        This will:
        - Run T-01 through T-18 sequentially.
        - Skip tests whose prerequisites are not met (via should_skip_test()).
        - For each test: create pipeline, run 7 prompt bands × (2 warmup + 5 measured) = 49 generations.
        - Write evidence atomically after each test completes.
        - Evaluate quality gates after all tests finish.
        - Output final disposition to stdout as JSON.

        EXPECTED SKIP PATTERNS:
        - T-05 (14B + EAGLE-3): Runs if EAGLE-3 conversion succeeded, skips otherwise.
        - T-07 (8B + EAGLE-3): Same as T-05.
        - T-13, T-14, T-15, T-16 (NPU cross-device): SKIPPED with CROSS_DEVICE_DRAFT_DISABLED_FATAL_NATIVE_ABORT.
          This is EXPECTED and CORRECT per the bug 3 disposition.
        - T-17, T-18 (CPU fallback): May skip with CPU_FALLBACK_NOT_REQUIRED_NPU_SUPPORTED
          since NPU discovery showed supported=true. This is expected.
        
        EXPECTED COMPLETIONS: T-01, T-02, T-03, T-04, T-06, T-08, T-09, T-10, T-11, T-12
        (10 tests minimum). T-05 and T-07 complete if EAGLE-3 conversion succeeded.
      </step>

      <step name="4.3 Monitor (Background)">
        The benchmark will consume 100% of one CPU core and 8-10 GB of GPU memory.
        It will run for several hours. Start it as a background process and periodically
        check the evidence file for progress:
        ```python
        import json
        with open("phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json") as f:
            data = json.load(f)
        print(f"Tests completed: {len(data.get('tests', []))}")
        for t in data.get("tests", []):
            print(f"  {t['id']}: {t.get('status')} {t.get('skip_reason', '')}")
        ```
      </step>
    </phase>

    <phase number="5" name="Evidence Assessment and Commit">
      <description>
        After the benchmark completes, verify evidence quality and commit.
      </description>

      <step name="5.1 Evidence Validation">
        Read the final evidence matrix and verify:
        - At least 10 tests completed (T-01 through T-12 minus NPU skips).
        - Quality gate evaluation is populated.
        - No test has status "aborted_memory_warning" (would indicate RSS exceeded 26 GB).
        - Band-512 TPS values look reasonable (T-01 14B baseline should be ~5-6 tps without
          GPU contamination, T-06 8B baseline should be ~8-10 tps).
      </step>

      <step name="5.2 Commit">
        Stage and commit all changes:
        ```
        git add -A
        git commit -m "P5-005a full rerun: {disposition}

        - Fixed should_skip_test() eagle ordering + ternary precedence
        - EAGLE-3 acquisition: {8B status}, {14B status}
        - Tests completed: {count}/18, skipped: {skip_count}
        - T-01 (14B baseline) tps@512: {value}
        - T-06 (8B baseline) tps@512: {value}
        - Best config: {test_id} at {tps} tps@512
        - Quality gate disposition: {disposition}
        - Evidence: p5_005a_unified_draft_feasibility_matrix.json
        - EAGLE-3 evidence: p5_005a_eagle3_acquisition.json"
        ```
      </step>

      <step name="5.3 Summary Report">
        Print a clear summary of results to the chat for the Lead Architect to review:
        - Disposition
        - All test results with tps@512 and speedup vs baseline
        - Which tests were skipped and why
        - EAGLE-3 acquisition outcome
        - Memory utilization summary
        - Total benchmark duration
      </step>
    </phase>

  </execution_plan>

  <harness_constraint>FULL_HARNESS_PRESENT</harness_constraint>
  <harness_note>
    The harness (run_p5_feasibility_005a.py) runs the complete 18-test matrix autonomously.
    After bug fixes in Phase 1, it should execute correctly with no modifications beyond
    the should_skip_test() fix. The harness writes evidence atomically after each test.
    It has NO resume logic — if the process dies mid-run, all data from that run is lost.
    This is why the Modern Standby fix verification in Phase 0 is MANDATORY.
  </harness_note>

  <evidence_quality_gate>
    <minimum_runs>5 measured runs per prompt band per test</minimum_runs>
    <warmup_runs>2 warmup runs before measurement</warmup_runs>
    <prompt_bands>[128, 256, 512, 1024, 2048, 3072, 4096]</prompt_bands>
    <max_new_tokens>128</max_new_tokens>
    <reproducibility>All 5 measured runs should complete without error (valid_count=5).</reproducibility>
    <rss_ceiling>RSS must not exceed 15,507 MB. Flagged as OVER_BUDGET if exceeded.</rss_ceiling>
    
    <disposition_paths>
      <path name="QWEN3_14B_WITH_SPEC_DECODING">14B >= 8 tps@512 AND speculative >= 1.3x baseline</path>
      <path name="QWEN3_14B_CONFIRMED">14B >= 8 tps@512 without speculative boost</path>
      <path name="QWEN3_14B_MARGINAL">14B 6-8 tps@512</path>
      <path name="QWEN3_8B_WITH_SPEC_DECODING">8B >= 8 tps@512 AND speculative >= 1.3x baseline</path>
      <path name="QWEN3_8B_FALLBACK">8B >= 8 tps@512</path>
      <path name="BOTH_INFEASIBLE">Neither model reaches 8 tps@512</path>
      <path name="INSUFFICIENT_EVIDENCE">Quality gates G-01/G-03/G-04/G-07 not all met</path>
    </disposition_paths>

    <eagle3_disposition>
      <if_framework_unsupported>
        Record specific error. T-05/T-07 status = "skipped" with FRAMEWORK_NOT_SUPPORTED
        or EAGLE3_NOT_CONVERTIBLE. This does NOT invalidate the overall study — the other
        16 tests still determine the primary disposition.
      </if_framework_unsupported>
      <if_successful>
        T-05/T-07 results are included in the quality gate evaluation. If EAGLE-3 provides
        >= 1.3x speedup vs baseline, it contributes to the *_WITH_SPEC_DECODING dispositions.
      </if_successful>
    </eagle3_disposition>
  </evidence_quality_gate>

  <documentation_updates_mandatory>
    <item>phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json — primary evidence (generated by harness)</item>
    <item>phase2_gates/evidence/p5_005a_eagle3_acquisition.json — EAGLE-3 acquisition evidence (generated by Phase 2-3)</item>
    <item>Do NOT update IMPLEMENTATION_PLAN.md or POST_OPERATIONAL_MATURATION_LEDGER.md — the SDO will handle that.</item>
  </documentation_updates_mandatory>

  <test_and_validation_targets>
    <compile>python -m py_compile phase2_gates\scripts\run_p5_feasibility_005a.py</compile>
    <test>python -m pytest tests\ -x -q</test>
    <benchmark>.venv\Scripts\python.exe phase2_gates\scripts\run_p5_feasibility_005a.py</benchmark>
  </test_and_validation_targets>

  <deliverables>
    <item>Bug fix in run_p5_feasibility_005a.py should_skip_test() — eagle check before generic draft check, ternary precedence fixed</item>
    <item>phase2_gates/scripts/acquire_eagle3_models.py — EAGLE-3 acquisition script</item>
    <item>phase2_gates/evidence/p5_005a_eagle3_acquisition.json — EAGLE-3 acquisition evidence</item>
    <item>phase2_gates/evidence/p5_005a_unified_draft_feasibility_matrix.json — full benchmark evidence (18 tests)</item>
    <item>models/eagle3-qwen3-8b/ — converted EAGLE-3 head for 8B (if convertible)</item>
    <item>models/eagle3-qwen3-14b/ — converted EAGLE-3 head for 14B (if convertible)</item>
  </deliverables>

  <commit_template>
    P5-005a full rerun: {disposition}

    - Fixed should_skip_test() eagle check ordering + ternary precedence bug
    - EAGLE-3 8B: {acquired/failed} from {repo}
    - EAGLE-3 14B: {acquired/failed} from {repo}
    - Tests completed: {count}/18, skipped: {skip_count}
    - T-01 14B baseline tps@512: {value}
    - T-06 8B baseline tps@512: {value}
    - Best TPS@512: {test_id} at {value}
    - Quality gate disposition: {disposition}
    - Evidence: p5_005a_unified_draft_feasibility_matrix.json
    - EAGLE-3 evidence: p5_005a_eagle3_acquisition.json
    - Modern Standby fix verified: PlatformAoAcOverride=0 active
  </commit_template>

  <role_boundary>
    You are an Execution Agent. Execute this milestone ONLY. Do NOT generate SDO prompts,
    continuation prompts, or planning documents. If scope is insufficient, fail closed
    and state what is missing.
  </role_boundary>

</execution_prompt>
```
