## Independent reproduction with issue-aligned export stack

Hi @diego-villalobos / OpenVINO team — confirming your Apr 24 finding from a separate Lunar Lake host with a 3-cell matrix designed to isolate exporter vs. compiler.

### Environment

| Field | Issue post (Mar 2026) | This reproduction |
|---|---|---|
| OpenVINO | `2026.0.0-20965` | `2026.0.0-20965-c6d6a13a886-releases/2026/0` ✅ |
| OpenVINO GenAI | `2026.0.0.0-2820` | `2026.0.0.0-2820-dab5b993a38` ✅ |
| `transformers` (export venv) | `4.51.3` | `4.51.3` ✅ |
| `optimum-intel` (export venv) | `1.27.0` | `1.27.0` ✅ |
| `nncf` (export venv) | `3.0.0` | `3.0.0` ✅ |
| Host | LNL | Intel Core Ultra 7 258V (LNL), Windows 11 |
| GPU driver | `32.0.101.6987` | `32.0.101.8735` (4/19/2026, **newer**) |
| NPU driver | `32.0.100.4514` | `32.0.100.4724` (3/18/2026, **newer**) |

Exports were produced in a dedicated `.export-venv` pinned to the issue's exact stack to eliminate exporter-version drift as a confound. The NPU compile step uses `openvino_genai` (`2026.0.0.0-2820`) directly.

Model: `Qwen/Qwen3-0.6B`, weight-format `int4`, group-size `128`, ratio `1.0`. Used as the **draft** in `LLMPipeline(target=Qwen3-14B/GPU, draft=Qwen3-0.6B/NPU)` speculative decoding setup.

### Reproduction matrix

| Cell | Export args | Stateful? | Compile outcome |
|---|---|---|---|
| **A** | `--weight-format int4 --group-size 128 --ratio 1.0` (no `--task`, no `--disable-stateful`) | stateful (default) | `StopLocationVerifierPass Pass failed : Found 40 duplicated names` |
| **B** | `--task text-generation-with-past` (issue command) | stateful | `StopLocationVerifierPass Pass failed : Found 40 duplicated names` |
| **C** | `--task text-generation-with-past --disable-stateful` | stateless | `Stateful models without 'beam_idx' input are not supported in StatefulToStateless transformation` |

### Key findings

1. **Cells A and B both reproduce `StopLocationVerifierPass: Found 40 duplicated names` exactly as @diego-villalobos reported on Apr 24.** Cell B is a fresh export produced with the **exact** optimum-intel `1.27.0` + nncf `3.0.0` + transformers `4.51.3` stack from the issue, so this rules out exporter-version drift as the cause. The bug is in the NPU compiler (vpux-compiler), not the exporter.

2. **Cell C surfaces a different failure path.** Even with `--disable-stateful`, the resulting model still has `beam_idx` listed as an input but is treated as stateful by the `StatefulToStateless` pass, which then rejects it. So `--disable-stateful` is not a viable workaround on this version pair.

3. **Original SIGABRT (`Aborted (core dumped)`) reported in issue #34450 is no longer observed.** All three cells fail with clean Python `RuntimeError`s now. The crash has been converted to a structured error — but the underlying compile failure persists.

4. **Cell A and Cell B exports differ in produced module name** (`Model1106_kv1152_FCEW000__0` vs. `Model0_kv1152_FCEW000__0`) but both fail the same StopLocationVerifierPass. Cell A's draft input list and Cell B's draft input list are **identical** (`['input_ids', 'attention_mask', 'position_ids', 'beam_idx']`) — confirming that whatever export-time difference produced different module IDs has no functional impact on the failing pass.

### Artifacts

Per-cell SHA256 of `openvino_model.xml` / `openvino_model.bin`, full crash logs, and the matrix JSON are available on request. Crash log tails are included below for grep-ability.

```
[ERROR] [vpux-compiler] Got Diagnostic at loc(fused<{name = "module", type = "Module"}>["module"]) :
StopLocationVerifierPass Pass failed : Found 40 duplicated names after full verification
loc(fused<{name = "module", type = "Module"}>["module"]): error: StopLocationVerifierPass Pass failed :
Found 40 duplicated names after full verification
[ERROR] [vpux-compiler] Failed Pass StopLocationVerifierPass on Operation
loc(fused<{name = "module", type = "Module"}>["module"])
RuntimeError: Exception from src\inference\src\cpp\core.cpp:113:
Exception from src\inference\src\dev\plugin.cpp:53:
Exception from src\plugins\intel_npu\src\plugin\npuw\compiled_model.cpp:516:
Failed to compile Model0_kv1152_FCEW000__0 for all devices in [NPU]
```

### Suggested next steps

- Since Cell B reproduces with the exact issue stack, the question is whether vpux-compiler can be patched to deduplicate names emitted by NNCF INT4 weight compression at `--ratio 1.0` for Qwen3-0.6B's per-tensor name layout.
- Happy to re-run with any specific `--ov-config` overrides, `NPU_COMPILER_TYPE` flags, or against a 2026.1.0/nightly build if helpful.

