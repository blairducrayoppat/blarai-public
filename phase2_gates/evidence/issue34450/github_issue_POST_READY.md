<!-- ============================================================ -->
<!--  FIELD: Title                                               -->
<!-- ============================================================ -->

[Bug][NPU] LLMPipeline(ir, "NPU") silently accepts INT8 weight-only IR (no error, no warning) then dies with uncatchable 0xC0000005 at generate() — missing construct-time precision guard


<!-- ============================================================ -->
<!--  FIELD: Issue description                                   -->
<!-- ============================================================ -->

## Summary

An OV 2026.0.0 IR exported with `optimum-cli export openvino --weight-format int8 --task text-generation-with-past` from `Qwen/Qwen3-0.6B`:

- **Loads and constructs** without error or warning via `openvino_genai.LLMPipeline(ir, "NPU")` (16.45 s cold). Verbose log shows the stateful LLM submodel landed on `NPU: Intel(R) AI Boost`, no fallback to CPU/GPU, no plugin diagnostic.
- **Crashes uncatchably** with Windows `STATUS_ACCESS_VIOLATION` `0xC0000005` (process exit code `-1073741819`) inside the first `pipe.generate(prompt, max_new_tokens=16)` call. No Python traceback. No `PYTHON_EXCEPTION` line. No `[ERROR]` from the NPU plugin. The child process simply dies during decode.
- **Same IR, same harness, GPU instead of NPU** → `GENERATE_OK tokens=16 elapsed=0.33s` cleanly. The IR is structurally valid.

Filed separately from #34450 at @diego-villalobos's request. #34450 covered an INT4 NPUW-partition `StopLocationVerifierPass` failure and was closed as expected behavior. INT8 weight-only is outside the [documented NPU LLM support matrix](https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html) (which requires `--sym` INT4); this issue is about the *failure mode*, not a request to support INT8.

## Expected behavior

One of:

- `LLMPipeline(ir, "NPU")` raises a Python exception at construct time stating that the IR's weight precision is outside the supported NPU LLM matrix, OR
- `pipe.generate(...)` raises a catchable Python exception with a plugin-side diagnostic, OR
- The pipeline runs to completion.

## Actual behavior

- `LLMPipeline(ir, "NPU")` constructs successfully in 16.45 s. Verbose log reports `EXECUTION_DEVICES: NPU: Intel(R) AI Boost`, `NETWORK_NAME: Model0_prefill`, `INFERENCE_PRECISION_HINT: f16`, `LOADED_FROM_CACHE: NO`. No warning, no fallback, no `[ERROR]`.
- The first `pipe.generate(prompt, max_new_tokens=16)` call terminates the process with `STATUS_ACCESS_VIOLATION` `0xC0000005` (exit code `-1073741819`).
- No Python exception is raised — the crash is uncatchable from Python.
- No NPU plugin / `vpux-compiler` / `IE::FrontEnd` diagnostic is emitted to stdout/stderr at any log level tested (see Diagnostics attempted).
- Windows Application Error log (Event ID 1000) records two crash entries at the identical fault site: faulting module `openvino.dll` v`2026.0.0.20965`, offset `0x0000000000077d86`. Consistent offset across entries confirms a deterministic code path, not a transient hardware condition.
- Crash is reproducible 3/3 consecutive runs with the same exit code.
- Crash occurs with `--tokens 1` (single decode step), ruling out a long-sequence accumulation as the trigger.

## Diagnostics attempted

### Log-level matrix

| Run | Environment | Result | New NPU diagnostic? |
|-----|-------------|--------|---------------------|
| Baseline (existing) | `OPENVINO_LOG_LEVEL=3` | Exit `-1073741819` | — |
| OV level 5 | `OPENVINO_LOG_LEVEL=5` | Exit `-1073741819` | None — crash behavior identical; no NPU-side error emitted |
| NPU log level (integer) | `OV_NPU_LOG_LEVEL=5` | Exit `1` (Python exception at construct) | Plugin rejects the variable: *"Failed to parse 'LOG_LEVEL' option: Unsupported log level: 5"* |
| NPU log level sweep | `OV_NPU_LOG_LEVEL` = 0, 1, 2, 3, 4, 5, `DEBUG`, `TRACE`, `INFO`, `WARNING` | Exit `1` for all values | All rejected at construct — `OV_NPU_LOG_LEVEL` is unusable in OV 2026.0.0 regardless of value |
| Both at max | `OPENVINO_LOG_LEVEL=5` + `OV_NPU_LOG_LEVEL=5` | Inherits `OV_NPU_LOG_LEVEL` construct-fail | — |

`OV_NPU_LOG_LEVEL` with any value prevents the NPU plugin from loading in this build. `OPENVINO_LOG_LEVEL=5` is usable but produces no additional NPU-specific diagnostic beyond level 3.

### Determinism

3/3 consecutive runs exit with `-1073741819`. No session-state or warm-up dependency observed.

### Prefill-vs-decode scope

`repro_int8_npu.py --tokens 1` crashes with the same exit code `-1073741819`. The fault occurs at the first decode step, not as a function of sequence length.

### WER crash dump

Attempted to enable WER LocalDumps for `python.exe` via `HKCU\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\python.exe`. No dump was produced: the `STATUS_ACCESS_VIOLATION` in `openvino.dll` terminates the process before the user-mode WER fault handler fires. The faulting module, version, and fault offset are captured from the Windows Application Error log (see Evidence on file). A kernel-mode capture would be needed to produce a `.dmp`; available to Intel on request.

## What the matrix already rules in/out

This was discovered as part of the #34450 expansion matrix. The relevant cells (full matrix and per-cell logs available on request, or see the closeout comments on #34450):

| Cell | Export | nncf scheme | NPU `LLMPipeline` construct | NPU `generate(16 tok)` | GPU control |
|---|---|---|---|---|---|
| G-B-sym | `--group-size 128 --sym` | int4_sym, gs=128 | OK 8.58 s | OK 0.97 s ✓ | n/a |
| G-H | `--group-size -1` | int4_asym, per-channel | OK 8.38 s | OK 2.80 s ✓ | n/a |
| **G-I** (this issue) | `--weight-format int8` | **int8_asym, per-channel** | **OK 16.45 s** | **CRASH 0xC0000005 (exit -1073741819)** | **OK 0.33 s, 16 tok ✓** |

The failure is specific to **NPU + INT8 weight-only at decode time**. The same NPU + driver + OV build runs both INT4 paths (documented `--sym` recipe and undocumented channel-wise asym) end-to-end on the same model.

**Open question:** A second INT8 weight-only IR on a different model architecture was not tested in this filing. Per Intel's documentation, INT8 weight-only is outside the supported NPU LLM matrix generally (not specific to Qwen3-0.6B); what is untested is whether the *specific failure mode* — silent construct success followed by an uncatchable native crash — is consistent across other INT8 models, or whether a different model would instead produce a clean error or fail at a different point.

## Suggested resolution

A construct-time precision guard in the NPUW LLM path that rejects unsupported weight formats with a clear Python exception would close this issue. Suggested message:

> `Configuration not supported on NPU: weight format INT8 weight-only is outside the supported NPU LLM matrix. Use --sym INT4 (--group-size -1 or 128) per https://docs.openvino.ai/2026/openvino-workflow-generative/inference-with-genai/inference-with-genai-on-npu.html`

This matches the resolution pattern accepted on #34450 (clean config rejection at the boundary, rather than opaque deep-pipeline failure).

Regardless of whether INT8 weight-only is on the NPU LLM roadmap: the underlying defect is the silent-construct → uncatchable-native-crash transition — the pipeline accepts the model without error at construct time, then terminates the process with a native access violation at the first decode call. A catchable exception at either boundary would be a safe fallback even if the weight format remains unsupported.

## Cross-references

- #34450 — closed as expected behavior; this is the INT8 follow-up Diego asked us to file separately.
- #34617 — separate NPU plugin dynamic-shape limitation; orthogonal to this issue (we verified direct `Core().compile_model(ir, "NPU")` on `cell_i` fails at the same `to_shape was called on a dynamic shape` location as every other stateful LLM IR, regardless of weight format — that's the #34617 path, not this one).

## Evidence on file (available on request, can attach to this issue)

Artifacts collected locally, available to attach on request:

**Original evidence**

- `cell_i_export.log` — `optimum-cli export` output with NNCF bitwidth table
- `cell_i_compile.log` — direct `Core().compile_model(ir, "NPU")` output (fails at `to_shape` — #34617 territory, included for completeness)
- `cell_g_i_npuw.log` — `LLMPipeline(ir, "NPU")` construct-only, succeeds (16.45 s)
- `cell_g_i_npuw_logged.log` — same with `OPENVINO_LOG_LEVEL=3`, confirms `EXECUTION_DEVICES: NPU` and no fallback
- `cell_i_e2e.log` — full end-to-end run, captures CONSTRUCT_OK then native crash
- `cell_i_gpu.log` — same IR, GPU instead of NPU, `GENERATE_OK tokens=16 elapsed=0.33s` ✓
- IR artifact — `openvino_model.{xml,bin}` with sha256s listed in Step 1; reproducible from the Step 1 export command

**Additional diagnostic evidence**

- `repro_int8_npu.py` — standalone reproducer script; byte-identical to the inline code block above
- `cell_i_event_viewer.txt` — Windows Application Error (Event ID 1000) XML; faulting module `openvino.dll` v`2026.0.0.20965`, offset `0x0000000000077d86` (two consistent entries at the same fault site)
- `cell_i_npu_ovlevel5.log` — repro with `OPENVINO_LOG_LEVEL=5`; crash confirmed, no additional NPU diagnostic
- `cell_i_npu_npulevel5.log` — repro with `OV_NPU_LOG_LEVEL=5`; NPU plugin rejects the variable at construct (*"Unsupported log level: 5"*)
- `cell_i_npu_bothlevel5.log` — log-level matrix note: `OV_NPU_LOG_LEVEL` unusable in OV 2026.0.0 with any integer or string value
- `cell_i_npu_determinism.log` — 3 consecutive NPU crash runs; all exit `-1073741819`
- `cell_i_npu_tokens1.log` — repro with `--tokens 1`; crash confirmed at the first decode step
- `cell_i_pipshow.txt` — `pip show openvino openvino-genai` confirming PyPI wheel install source
- `cell_i_driver_currency.txt` — installed vs. latest GPU/NPU driver version comparison
- `cell_i_wer_dump_note.txt` — WER LocalDumps attempt outcome; no `.dmp` captured (crash bypasses user-mode WER; faulting module/offset available from Event Viewer)

The obvious additional log-level variants have been run and are reported above. `OPENVINO_LOG_LEVEL=5` produces no new NPU diagnostic. `OV_NPU_LOG_LEVEL` is unusable in this build — any value causes the NPU plugin to fail at construct. If a working plugin-side diagnostic variable exists that is not enumerated here, we will re-run with it on request.

---

## AI Usage Policy disclosure

This issue body and the reproduction harness were drafted with assistance from a coding agent (GitHub Copilot) acting on direction from the human author. All evidence (logs, sha256s, exit codes, timings, IR fingerprints, environment table) was generated by running the harness in our local environment; the agent did not fabricate values. The human author reviewed the technical claims for accuracy against the underlying logs before posting. This disclosure is included per the OpenVINO project's AI Usage Policy.


<!-- ============================================================ -->
<!--  FIELD: Step-by-step reproduction                           -->
<!-- ============================================================ -->

### Environment

| Component | Compile-time `.venv` (this stack) | Export-time `.export-venv` |
|---|---|---|
| openvino | `2026.0.0` | `2026.0.0` |
| openvino-genai | `2026.0.0.0` | — |
| optimum-intel | `1.27.0.dev0+d8864c45` (editable) | `1.27.0` |
| optimum | `2.1.0.dev0` | `2.1.0` |
| transformers | `5.3.0` | `4.51.3` (Intel's recommended NPU pin) |
| nncf | `3.0.0` | `3.0.0` |
| torch | `2.10.0` | `2.6.0+cpu` |

**Host**

- Windows 11 Pro 26100
- Intel Core Ultra 7 258V (Lunar Lake)
- Arc 140V GPU driver: `32.0.101.6987` (2025-07-29); latest publicly available: `32.0.101.8735`
- AI Boost NPU driver: `32.0.100.4724` (2026-03-19); current — Intel Driver & Support Assistant confirms no newer version available as of 2026-05-01
- openvino / openvino-genai install source: PyPI wheel (`pip install openvino==2026.0.0 openvino-genai==2026.0.0.0`; confirmed via `pip show` — standard site-packages location, no `direct_url.json`, no editable install)
- No OV compiler cache present (`%LOCALAPPDATA%\openvino_cache` does not exist; runs are cold-compile)

### Step 1 — Export the IR (separate venv, optimum-intel `1.27.0` + transformers `4.51.3`)

```powershell
optimum-cli export openvino `
  --model Qwen/Qwen3-0.6B `
  --weight-format int8 `
  --task text-generation-with-past `
  exports\cell_i
```

Resulting IR fingerprints (deterministic for the inputs above):

- `openvino_model.xml` sha256: `6e662ae7ed0e855460c939d266f52b3b7383e2535a717c2cb13da4bc19324f20`
- `openvino_model.bin` sha256: `2ac6e241235fd70e110ae90771ffc9ec8ff11de70ab6f17992d574e156654a73`

NNCF reports the expected `int8_asym, per-channel` weight distribution:

```
+---------------------------+-----------------------------+----------------------------------------+
| Weight compression mode   | % all parameters (layers)   | % ratio-defining parameters (layers)   |
+===========================+=============================+========================================+
| int8_asym, per-channel    | 100% (197 / 197)            | 100% (197 / 197)                       |
+---------------------------+-----------------------------+----------------------------------------+
```

### Step 2 — Run the harness on NPU

A subprocess-isolated harness is required because the failure is an uncatchable native crash; without isolation the parent process dies too. Minimal repro (`repro_int8_npu.py`):

```python
"""Subprocess-isolated NPU repro for INT8 weight-only Qwen3-0.6B.

Constructs LLMPipeline(ir, "NPU"), then attempts a 16-token generate().
Construct succeeds; the generate() call dies with native 0xC0000005.
"""
from __future__ import annotations
import argparse, sys, time, traceback
from pathlib import Path

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ir", required=True, type=Path)
    p.add_argument("--device", default="NPU", choices=["CPU", "GPU", "NPU"])
    p.add_argument("--prompt", default="The capital of France is")
    p.add_argument("--tokens", type=int, default=16)
    args = p.parse_args()

    import openvino_genai as ov_genai
    from openvino_genai import LLMPipeline

    print(f"READY device={args.device} ir={args.ir}", flush=True)
    t0 = time.monotonic()
    try:
        pipe = LLMPipeline(str(args.ir), args.device)
    except BaseException as exc:
        print(f"PYTHON_EXCEPTION:{type(exc).__name__}:{exc}".replace("\n", " | "),
              file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1
    print(f"CONSTRUCT_OK elapsed={time.monotonic()-t0:.2f}s", flush=True)

    t1 = time.monotonic()
    try:
        out = pipe.generate(args.prompt, max_new_tokens=args.tokens)
    except BaseException as exc:
        print(f"PYTHON_EXCEPTION:{type(exc).__name__}:{exc}".replace("\n", " | "),
              file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1
    print(f"GENERATE_OK tokens={args.tokens} elapsed={time.monotonic()-t1:.2f}s "
          f"output={str(out).replace(chr(10),' | ')!r}", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

Driver script (run from a parent process so the native crash is captured as an exit code, not a process kill):

```powershell
$env:OPENVINO_LOG_LEVEL = "3"

# NPU — fails
python repro_int8_npu.py --ir exports\cell_i --device NPU --tokens 16
echo "NPU exit=$LASTEXITCODE"

# GPU control — succeeds
python repro_int8_npu.py --ir exports\cell_i --device GPU --tokens 16
echo "GPU exit=$LASTEXITCODE"
```

### Step 3 — Observed behavior

**NPU run (fails):**

```
READY device=NPU ir=exports\cell_i
[verbose log: tokenizer/detokenizer on CPU as expected,
 Stateful LLM model with EXECUTION_DEVICES: NPU,
 NETWORK_NAME: Model0_prefill, INFERENCE_PRECISION_HINT: f16,
 NPU: Intel(R) AI Boost]
CONSTRUCT_OK elapsed=16.45s
NPU exit=-1073741819
```

- No `PYTHON_EXCEPTION` line.
- No `GENERATE_OK` line.
- No `[ERROR]` from `vpux-compiler` or NPU plugin.
- Exit code `-1073741819` = `0xC0000005` STATUS_ACCESS_VIOLATION.

**GPU control (succeeds, same IR):**

```
READY device=GPU ir=exports\cell_i
CONSTRUCT_OK elapsed=~6s
GENERATE_OK tokens=16 elapsed=0.33s output='<think> | Okay, the user is asking about the capital of France. Let me'
GPU exit=0
```

This rules out IR malformation as the cause — the same IR generates correctly on GPU.


<!-- ============================================================ -->
<!--  FIELD: Relevant log output                                  -->
<!--  (GitHub auto-wraps in code block — paste as plain text)    -->
<!-- ============================================================ -->

NPU run (fails):

READY device=NPU ir=exports\cell_i
[verbose log: tokenizer/detokenizer on CPU as expected, Stateful LLM model with EXECUTION_DEVICES: NPU, NETWORK_NAME: Model0_prefill, INFERENCE_PRECISION_HINT: f16, NPU: Intel(R) AI Boost]
CONSTRUCT_OK elapsed=16.45s
NPU exit=-1073741819

No PYTHON_EXCEPTION line. No GENERATE_OK line. No [ERROR] from vpux-compiler or NPU plugin.
Exit code -1073741819 = 0xC0000005 STATUS_ACCESS_VIOLATION.
Windows Event ID 1000: faulting module openvino.dll v2026.0.0.20965, offset 0x0000000000077d86 (two consistent entries).

GPU control (succeeds, same IR):

READY device=GPU ir=exports\cell_i
CONSTRUCT_OK elapsed=\~6s
GENERATE_OK tokens=16 elapsed=0.33s output='<think> | Okay, the user is asking about the capital of France. Let me'
GPU exit=0
