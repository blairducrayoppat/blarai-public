# OV 2026.1.0 retest of issue openvino#35641

Date: 2026-05-12
Operator: Guide-#11 retest agent
Purpose: Confirm or refute Intel engineer `diego-villalobos`'s claim that the
INT8 weight-only NPU crash does not reproduce on OpenVINO 2026.1.0.

## 1. Environment

- **Host**: Windows 11 Pro
- **CPU**: Intel(R) Core(TM) Ultra 7 258V (Lunar Lake)
- **GPU**: Intel(R) Arc(TM) 140V GPU (16GB) iGPU, driver `32.0.101.8724`
  (slightly newer than the `32.0.101.6987` cited in the original issue body;
  retest captured the installed driver as-is.)
- **NPU**: Intel(R) AI Boost, driver `32.0.100.4724` (matches original report)
- **Python**: 3.11.9
- **Isolated venv path**: `C:\Users\mrbla\.venv-ov2026.1` (outside BlarAI repo;
  the BlarAI runtime venv was not touched.)

Resolved package versions (verbatim from `pip show` / `python -c "import x; print(x.__version__)"`):

| Package | Version |
|---|---|
| openvino | `2026.1.0-21367-63e31528c62-releases/2026/1` |
| openvino_genai | `2026.1.0.0-2957-1dabb8c2255` |
| openvino-telemetry | `2025.2.0` |
| openvino_tokenizers | `2026.1.0.0` |
| optimum | `2.1.0` |
| optimum-intel | `1.27.0` |
| transformers | `4.57.6` |
| nncf | `3.1.0` |
| torch | `2.11.0` |

OpenVINO device enumeration:
```
available_devices: ['CPU', 'GPU', 'NPU']
CPU -> Intel(R) Core(TM) Ultra 7 258V
GPU -> Intel(R) Arc(TM) 140V GPU (16GB) (iGPU)
NPU -> Intel(R) AI Boost
```

## 2. IR fingerprints

- **XML path**: `C:\Users\mrbla\openvino-test-exports\qwen3-0.6b-int8-ov2026.1\openvino_model.xml`
  - size: `2,851,220` bytes
  - SHA256: `93D053E8D55CCDA5D2943510A43B90C440AACD2DEE28FE44BD321D92E5507CCB`
- **BIN path**: `C:\Users\mrbla\openvino-test-exports\qwen3-0.6b-int8-ov2026.1\openvino_model.bin`
  - size: `597,735,053` bytes
  - SHA256: `3FDDE9AC20058BBDF364C98DBE3508B8EDDFFD1D33A0D213D111159F826DC939`

Original 2026.0.0 fingerprints (from issue body) for comparison:
- XML SHA256: `6e662ae7ed0e855460c939d266f52b3b7383e2535a717c2cb13da4bc19324f20`
- BIN SHA256: `2ac6e241235fd70e110ae90771ffc9ec8ff11de70ab6f17992d574e156654a73`

The fingerprints **differ** between the 2026.0.0 and 2026.1.0 exports. This is
expected: a different NNCF release (`nncf 3.1.0` here vs. whatever shipped with
the 2026.0.0 PyPI install) and/or upstream HF weight refresh produces a bit-for-bit
different IR even at the same nominal `int8` weight format. The 2026.1.0 IR is
nevertheless a faithful Qwen3-0.6B INT8 weight-only export per NNCF's bitwidth
report (see §3) and is **proven valid** by a clean GPU control run (see §5).

## 3. Export details

Command:
```
optimum-cli export openvino \
  --model Qwen/Qwen3-0.6B \
  --weight-format int8 \
  --task text-generation-with-past \
  C:\Users\mrbla\openvino-test-exports\qwen3-0.6b-int8-ov2026.1
```

- Wall-clock: `38.06s` (HuggingFace weights cached from prior export — fresh-download time would be higher)
- Exit code: `0`
- NNCF bitwidth report (verbatim from log):
  ```
  Statistics of the bitwidth distribution:
  +---------------------------+-----------------------------+----------------------------------------+
  | Weight compression mode   | % all parameters (layers)   | % ratio-defining parameters (layers)   |
  +===========================+=============================+========================================+
  | int8_asym, per-channel    | 100% (197 / 197)            | 100% (197 / 197)                       |
  +---------------------------+-----------------------------+----------------------------------------+
  ```
  100% `int8_asym, per-channel` across 197/197 layers — matches the bitwidth
  distribution the original issue reported for the 2026.0.0 export.
- Warnings: TracerWarnings from `transformers.cache_utils`, `masking_utils`,
  `optimum.exporters.openvino.model_patcher`, and `sdpa_attention` (standard
  torch trace-time warnings; no error-level diagnostics). One deprecation
  notice: `` `torch_dtype` is deprecated! Use `dtype` instead! ``. None of these
  are believed material to the NPU crash.

Note: the initial export attempt invoked the exporter as a `python -m`
module (`python -m optimum.exporters.openvino ...`) exited `0` but produced
no output files due to a runpy warning. The successful invocation used
the `optimum-cli` console script. Both forms appear in the project's tooling
docs; the CLI form is more reliable.

## 4. NPU retest results (3 runs)

All three runs invoked:
```
python -u repro_int8_npu_2026.1.py \
  --ir <ir-dir> --device NPU --tokens 16
```

| Run | Exit code | Wall-clock | Construct elapsed | Generate elapsed | Last log line |
|---|---|---|---|---|---|
| 1 | `-1073741819` (`0xC0000005`) | 21.25s | 17.51s | crashed before GENERATE_OK | `CONSTRUCT_OK elapsed=17.51s` |
| 2 | `-1073741819` (`0xC0000005`) | 21.54s | 17.78s | crashed before GENERATE_OK | `CONSTRUCT_OK elapsed=17.78s` |
| 3 | `-1073741819` (`0xC0000005`) | 21.95s | 18.29s | crashed before GENERATE_OK | `CONSTRUCT_OK elapsed=18.29s` |

**3/3 crashes. Deterministic.** Exit code `-1073741819` is `0xC0000005`
(Windows Access Violation, native crash with no Python traceback) — identical
signature to the original 2026.0.0 report.

Each log captured the three pre-construct prints (READY, openvino version,
openvino_genai version) and the `CONSTRUCT_OK` line, then terminated. The
crash is therefore **inside `pipe.generate(...)`** (or in a worker thread spawned
by the NPU plugin during generation), not during `LLMPipeline(...)` construction.
This is a meaningful refinement vs. the original report's "construct + generate
crash" wording — at least on this build, construct succeeds in ~17-18s
(consistent with NPU model-compile overhead) and the access violation only
manifests once generation actually begins.

Wall-clock gap between `CONSTRUCT_OK` and process exit is roughly 3-4s in
all three runs, so the crash is fast and consistent.

## 5. GPU control result

Same IR, same script, same machine, only `--device GPU` differs.

```
READY device=GPU ir=C:\Users\mrbla\openvino-test-exports\qwen3-0.6b-int8-ov2026.1
openvino=2026.1.0-21367-63e31528c62-releases/2026/1
openvino_genai=2026.1.0.0-2957-1dabb8c2255
CONSTRUCT_OK elapsed=5.65s
GENERATE_OK tokens=16 elapsed=0.27s output='<think>\nOkay, the user is asking about the capital of France. I know'
```

- Exit code: `0`
- Wall-clock: `6.75s`
- Construct: `5.65s`
- Generate: `0.27s` for 16 tokens
- Output text is coherent (Qwen3-0.6B begins a `<think>` block, which is
  expected for an unconstrained Qwen3 generation).

The IR is verified-valid. The crash is **NPU-plugin-specific** on this hardware
+ driver + OpenVINO build combination.

## 6. Conclusion

**Crash reproduces in 2026.1.0? YES (3/3, deterministic).**

Diego's claim is **REFUTED on this hardware**:

- Hardware: Intel Core Ultra 7 258V (Lunar Lake), Intel AI Boost NPU
- NPU driver: `32.0.100.4724`
- OpenVINO: `2026.1.0-21367` / openvino_genai `2026.1.0.0-2957`
- Test: 3 consecutive `LLMPipeline(ir, "NPU") + pipe.generate(...)` invocations
  against a Qwen3-0.6B `--weight-format int8` export.
- Result: 3/3 native crashes with exit `0xC0000005`, all post-CONSTRUCT_OK,
  all during `generate()`.

Refinement of the original bug: `LLMPipeline(...)` construction on NPU
**now succeeds** in ~17-18s. The crash is no longer at pipeline construction
but at first-token generation. The original ticket's framing of "construct +
generate crash" should be tightened to "generate-time crash; construct
completes silently".

Possible explanations for why diego could not reproduce:
- Different host (e.g. a non-Lunar-Lake reference platform with a different
  NPU silicon or firmware revision)
- Different NPU driver release (the BKC NPU drivers Intel uses internally may
  differ from `32.0.100.4724`)
- Different OS image / Windows servicing branch — Windows kernel handling of
  NPU memory mapping may interact with the access violation site
- Different Qwen3-0.6B revision pulled from HF (less likely — the GPU run on
  the same IR succeeds, so the IR is well-formed; this is a plugin defect,
  not a model defect)

The "OpenVINO accepts an INT8 weight-only export and routes it to NPU silently
even though INT8 weight-only is outside the documented NPU-supported matrix"
**separable defect** is unaffected by these results — diego himself confirmed
INT8 weight-only is outside the supported NPU matrix, so silent acceptance
remains a real defect regardless of whether the downstream crash is fixed.

## 7. Implications for engagement comment v2

- The "I'll retest on 2026.1.0" promise in the v1 draft can be replaced with
  concrete data: "Retested on OV 2026.1.0 / openvino_genai 2026.1.0.0 with the
  exact same hardware and NPU driver; crash reproduces 3/3 with exit `0xC0000005`.
  The crash signature has migrated from pipeline-construction-time to
  generate-time — `LLMPipeline(ir, "NPU")` now returns successfully in ~18s,
  then `pipe.generate(prompt, cfg)` access-violates within a few seconds."
- This is **stronger data** than the v1 promise; it lets the GitHub comment
  open with an empirical update rather than a request for cross-check.
- The separable defect (silent acceptance of an unsupported INT8 weight-only
  config on NPU) framing stays valid and is the cleaner contribution target:
  whether or not the crash is later fixed, a `NOT_IMPLEMENTED` /
  `unsupported configuration` guard at pipeline-load time would have prevented
  the user from ever observing the access violation.
- If anything, the new "construct succeeds, generate crashes" finding
  strengthens the silent-acceptance case: the NPU plugin clearly compiles the
  graph without complaint and only collapses once it tries to execute. A
  capability check at compile time has even more value than at load time.

## 8. Notes / anomalies

- The first export invocation (`python -m optimum.exporters.openvino ...`)
  emitted only a runpy `RuntimeWarning` and exited `0` without producing any
  output files. The successful invocation used the `optimum-cli` console script.
  This is a tooling defect orthogonal to the NPU issue but worth noting for
  anyone trying to reproduce.
- The repro script was unexpectedly missing from disk between NPU run 2 and
  run 3 in an earlier attempt (path returned "file not found" despite Write
  reporting success and the script having executed minutes prior). Cause not
  diagnosed; possibly an editor/sync race. The retest was completed by
  copying the repro script to a second location outside the repo
  (`C:\Users\mrbla\openvino-test-exports\repro_int8_npu_2026.1.py`) and
  running from there. The committed copy in
  `phase1-ea17-coordinate-with-intel/repro_int8_npu_2026.1.py` is byte-identical.
- A second disappearance of the repro script (and the retest report itself)
  was observed after the retest agent completed and the parent Guide tried
  to commit. Likely root cause: SDO `wake_launcher` post-session auto-stash
  during a wake event the Guide-side pause did not block (the wake_launcher
  may not consult the canonical devplatform-side `state.json` due to the
  path-defect tracked by Vikunja #453). The retest report was recovered
  from in-context Read history (this file); the repro script was recovered
  from the out-of-repo backup. Documented in STATUS.md §E4 anomaly A-NEW5.
- GPU driver on this host is `32.0.101.8724`, slightly newer than the
  `32.0.101.6987` cited in the original issue body. NPU driver is unchanged
  (`32.0.100.4724`). The crash is NPU-specific and the GPU control was clean,
  so the GPU driver bump is not believed to confound the result.
- All three NPU runs and the GPU run executed cleanly under the `Bash` /
  `PowerShell` tool harness; exit codes were captured via `$LASTEXITCODE`
  immediately after each invocation. Per-run log files are at
  `C:\Users\mrbla\openvino-test-exports\npu_run{1,2,3}.log` and
  `gpu_control.log` (outside the repo, not committed).
- Total retest wall-clock: ~7 minutes including venv setup, install, export,
  and four model runs.
