# Issue #34450 — Compile Matrix (Cells D–J)

_Generated: 2026-04-25T19:49:19Z_

## Environment

### Compile-time interpreter (.venv)

| Package | Version |
|---|---|
| python | `3.11.9` |
| openvino | `2026.0.0` |
| openvino-genai | `2026.0.0.0` |
| optimum | `2.1.0.dev0` |
| optimum-intel | `1.27.0.dev0+d8864c45` |
| transformers | `5.3.0` |
| nncf | `3.0.0` |
| torch | `2.10.0` |

### Export-time interpreter (.export-venv) — used to produce IR

| Package | Version |
|---|---|
| python | `3.11.9` |
| openvino | `2026.0.0` |
| openvino-genai | `None` |
| optimum | `2.1.0` |
| optimum-intel | `1.27.0` |
| transformers | `4.51.3` |
| nncf | `3.0.0` |
| torch | `2.6.0+cpu` |

### Host

- Windows 10 (AMD64)
- Intel64 Family 6 Model 189 Stepping 1, GenuineIntel

## Results

| Cell | Description | Device | Mode | ov_config | Outcome | Exit | Elapsed | Notes |
|---|---|---|---|---|---|---|---|---|
| D | Cell B IR, direct compile on CPU (validate IR) | CPU | direct | — | ok | 0 | 1.8s |  |
| E | Cell B IR, direct compile on GPU (validate IR) | GPU | direct | — | ok | 0 | 7.2s |  |
| F | Cell B IR, direct compile on NPU (raw, no NPUW) | NPU | direct | — | python_exception | 1 | 2.9s | Exception from src\inference\src\cpp\core.cpp:133: \| Exception from src\inference\src\dev\plugin.cpp:58: \| Exception from src\plugins\inte |
| G | Cell B IR, LLMPipeline on NPU (NPUW, no spec-decode wrapper) | NPU | llmpipeline | — | python_exception | 1 | 7.1s | Exception from src\inference\src\cpp\core.cpp:113: \| Exception from src\inference\src\dev\plugin.cpp:53: \| Exception from src\plugins\inte |
| H | Cell H IR (channel-wise INT4), direct compile on NPU | NPU | direct | — | python_exception | 1 | 2.7s | Exception from src\inference\src\cpp\core.cpp:133: \| Exception from src\inference\src\dev\plugin.cpp:58: \| Exception from src\plugins\inte |
| I | Cell I IR (INT8), direct compile on NPU | NPU | direct | — | python_exception | 1 | 2.8s | Exception from src\inference\src\cpp\core.cpp:133: \| Exception from src\inference\src\dev\plugin.cpp:58: \| Exception from src\plugins\inte |
| J1 | Cell B IR, direct compile on NPU with NPU_COMPILER_TYPE=MLIR | NPU | direct | NPU_COMPILER_TYPE=MLIR | python_exception | 1 | 0.6s | Exception from src\inference\src\cpp\core.cpp:133: \| Exception from src\inference\src\dev\plugin.cpp:58: \| Exception from src\plugins\inte |
| J2 | Cell B IR, direct compile on NPU with NPU_COMPILER_TYPE=DRIVER | NPU | direct | NPU_COMPILER_TYPE=DRIVER | python_exception | 1 | 2.9s | Exception from src\inference\src\cpp\core.cpp:133: \| Exception from src\inference\src\dev\plugin.cpp:58: \| Exception from src\plugins\inte |

## Per-cell log tails

### Cell D — Cell B IR, direct compile on CPU (validate IR)
- ir: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b`
- ir xml sha256: `467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7`
- ir bin sha256: `0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af`
- log: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\cell_d_compile.log`

```
# command: C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py --ir C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b --device CPU --mode direct
# started: 2026-04-25T19:48:49Z
# ir xml sha256: 467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7
# ir bin sha256: 0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af

READY mode=direct device=CPU ir=C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b
OK elapsed=1.56s
```

### Cell E — Cell B IR, direct compile on GPU (validate IR)
- ir: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b`
- ir xml sha256: `467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7`
- ir bin sha256: `0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af`
- log: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\cell_e_compile.log`

```
# command: C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py --ir C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b --device GPU --mode direct
# started: 2026-04-25T19:48:51Z
# ir xml sha256: 467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7
# ir bin sha256: 0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af

READY mode=direct device=GPU ir=C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b
OK elapsed=6.92s
```

### Cell F — Cell B IR, direct compile on NPU (raw, no NPUW)
- ir: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b`
- ir xml sha256: `467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7`
- ir bin sha256: `0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af`
- log: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\cell_f_compile.log`

```
# command: C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py --ir C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b --device NPU --mode direct
# started: 2026-04-25T19:48:58Z
# ir xml sha256: 467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7
# ir bin sha256: 0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af

READY mode=direct device=NPU ir=C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b
[ERROR] 15:49:01.317 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.embed_tokens/ov_ext::embedding/Convert_1' (type 'Convert'): input '0' bounds are '[9223372036854775807, 9223372036854775807]'
[ERROR] 15:49:01.318 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.embed_tokens/ov_ext::embedding/Gather' (type 'Gather'): input '1' bounds are '[9223372036854775807, 9223372036854775807]'
[ERROR] 15:49:01.318 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::pow/Power' (type 'Power'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
[ERROR] 15:49:01.318 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::mean/ReduceMean' (type 'ReduceMean'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
[ERROR] 15:49:01.318 [vpux-compiler] Got Diagnostic at loc(fused<{name = "__module.model.layers.0.input_layernorm/aten::mul/Multiply", type = "Multiply"}>["__module.model.layers.0.input_layernorm/aten::mul/Multiply"]) : Got non broadcastable dimensions pair : '9223372036854775807' and -9223372036854775808'
loc(fused<{name = "__module.model.layers.0.input_layernorm/aten::mul/Multiply", type = "Multiply"}>["__module.model.layers.0.input_layernorm/aten::mul/Multiply"]): error: Got non broadcastable dimensions pair : '9223372036854775807' and -9223372036854775808'
[ERROR] 15:49:01.319 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::mul/Multiply' (type 'Multiply'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
PYTHON_EXCEPTION:RuntimeError:Exception from src\inference\src\cpp\core.cpp:133: | Exception from src\inference\src\dev\plugin.cpp:58: | Exception from src\plugins\intel_npu\src\plugin\src\plugin.cpp:879: | Exception from src\plugins\intel_npu\src\compiler_adapter\src\ze_graph_ext_wrappers.cpp:405: | L0 pfnCreate2 result: ZE_RESULT_ERROR_INVALID_NULL_POINTER, code 0x78000007 - pointer argument may not be nullptr . [NPU_VCL] Compiler returned msg: | Exception from src\core\src\partial_shape.cpp:266: | to_shape was called on a dynamic shape. |  |  |  |  | 
Traceback (most recent call last):
  File "C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py", line 70, in main
    _cm = core.compile_model(str(xml), args.device, ov_config)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\mrbla\BlarAI\.venv\Lib\site-packages\openvino\_ov_api.py", line 646, in compile_model
    super().compile_model(model, device_name, {} if config is None else config),
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Exception from src\inference\src\cpp\core.cpp:133:
Exception from src\inference\src\dev\plugin.cpp:58:
Exception from src\plugins\intel_npu\src\plugin\src\plugin.cpp:879:
Exception from src\plugins\intel_npu\src\compiler_adapter\src\ze_graph_ext_wrappers.cpp:405:
L0 pfnCreate2 result: ZE_RESULT_ERROR_INVALID_NULL_POINTER, code 0x78000007 - pointer argument may not be nullptr . [NPU_VCL] Compiler returned msg:
Exception from src\core\src\partial_shape.cpp:266:
to_shape was called on a dynamic shape.





FAILED elapsed=2.33s
```

### Cell G — Cell B IR, LLMPipeline on NPU (NPUW, no spec-decode wrapper)
- ir: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b`
- ir xml sha256: `467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7`
- ir bin sha256: `0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af`
- log: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\cell_g_compile.log`

```
# command: C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py --ir C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b --device NPU --mode llmpipeline
# started: 2026-04-25T19:49:02Z
# ir xml sha256: 467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7
# ir bin sha256: 0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af

READY mode=llmpipeline device=NPU ir=C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b
[ERROR] 15:49:08.567 [vpux-compiler] Got Diagnostic at loc(fused<{name = "module", type = "Module"}>["module"]) : StopLocationVerifierPass Pass failed : Found 40 duplicated names after full verification
loc(fused<{name = "module", type = "Module"}>["module"]): error: StopLocationVerifierPass Pass failed : Found 40 duplicated names after full verification
[ERROR] 15:49:08.570 [vpux-compiler] Failed Pass StopLocationVerifierPass on Operation loc(fused<{name = "module", type = "Module"}>["module"])
PYTHON_EXCEPTION:RuntimeError:Exception from src\inference\src\cpp\core.cpp:113: | Exception from src\inference\src\dev\plugin.cpp:53: | Exception from src\plugins\intel_npu\src\plugin\npuw\compiled_model.cpp:516: | Failed to compile Model0_kv1152_FCEW000__0 for all devices in [NPU] |  |  | 
Traceback (most recent call last):
  File "C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py", line 78, in main
    _pipe = LLMPipeline(str(args.ir), args.device)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Exception from src\inference\src\cpp\core.cpp:113:
Exception from src\inference\src\dev\plugin.cpp:53:
Exception from src\plugins\intel_npu\src\plugin\npuw\compiled_model.cpp:516:
Failed to compile Model0_kv1152_FCEW000__0 for all devices in [NPU]



FAILED elapsed=6.47s
```

### Cell H — Cell H IR (channel-wise INT4), direct compile on NPU
- ir: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_h`
- ir xml sha256: `0628da3f9f23c35b95908a7cdab666b4a72785c62dced0fcb1e6f64d94b7dc7d`
- ir bin sha256: `7c6aff87c19938037fc1642d701c32b567ddbc3a957b021feb722a6cab0265f5`
- log: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\cell_h_compile.log`

```
# command: C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py --ir C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_h --device NPU --mode direct
# started: 2026-04-25T19:49:09Z
# ir xml sha256: 0628da3f9f23c35b95908a7cdab666b4a72785c62dced0fcb1e6f64d94b7dc7d
# ir bin sha256: 7c6aff87c19938037fc1642d701c32b567ddbc3a957b021feb722a6cab0265f5

READY mode=direct device=NPU ir=C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_h
[ERROR] 15:49:11.527 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.embed_tokens/ov_ext::embedding/Convert_1' (type 'Convert'): input '0' bounds are '[9223372036854775807, 9223372036854775807]'
[ERROR] 15:49:11.528 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.embed_tokens/ov_ext::embedding/Gather' (type 'Gather'): input '1' bounds are '[9223372036854775807, 9223372036854775807]'
[ERROR] 15:49:11.528 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::pow/Power' (type 'Power'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
[ERROR] 15:49:11.528 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::mean/ReduceMean' (type 'ReduceMean'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
[ERROR] 15:49:11.528 [vpux-compiler] Got Diagnostic at loc(fused<{name = "__module.model.layers.0.input_layernorm/aten::mul/Multiply", type = "Multiply"}>["__module.model.layers.0.input_layernorm/aten::mul/Multiply"]) : Got non broadcastable dimensions pair : '9223372036854775807' and -9223372036854775808'
loc(fused<{name = "__module.model.layers.0.input_layernorm/aten::mul/Multiply", type = "Multiply"}>["__module.model.layers.0.input_layernorm/aten::mul/Multiply"]): error: Got non broadcastable dimensions pair : '9223372036854775807' and -9223372036854775808'
[ERROR] 15:49:11.529 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::mul/Multiply' (type 'Multiply'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
PYTHON_EXCEPTION:RuntimeError:Exception from src\inference\src\cpp\core.cpp:133: | Exception from src\inference\src\dev\plugin.cpp:58: | Exception from src\plugins\intel_npu\src\plugin\src\plugin.cpp:879: | Exception from src\plugins\intel_npu\src\compiler_adapter\src\ze_graph_ext_wrappers.cpp:405: | L0 pfnCreate2 result: ZE_RESULT_ERROR_INVALID_NULL_POINTER, code 0x78000007 - pointer argument may not be nullptr . [NPU_VCL] Compiler returned msg: | Exception from src\core\src\partial_shape.cpp:266: | to_shape was called on a dynamic shape. |  |  |  |  | 
Traceback (most recent call last):
  File "C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py", line 70, in main
    _cm = core.compile_model(str(xml), args.device, ov_config)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\mrbla\BlarAI\.venv\Lib\site-packages\openvino\_ov_api.py", line 646, in compile_model
    super().compile_model(model, device_name, {} if config is None else config),
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Exception from src\inference\src\cpp\core.cpp:133:
Exception from src\inference\src\dev\plugin.cpp:58:
Exception from src\plugins\intel_npu\src\plugin\src\plugin.cpp:879:
Exception from src\plugins\intel_npu\src\compiler_adapter\src\ze_graph_ext_wrappers.cpp:405:
L0 pfnCreate2 result: ZE_RESULT_ERROR_INVALID_NULL_POINTER, code 0x78000007 - pointer argument may not be nullptr . [NPU_VCL] Compiler returned msg:
Exception from src\core\src\partial_shape.cpp:266:
to_shape was called on a dynamic shape.





FAILED elapsed=2.14s
```

### Cell I — Cell I IR (INT8), direct compile on NPU
- ir: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_i`
- ir xml sha256: `6e662ae7ed0e855460c939d266f52b3b7383e2535a717c2cb13da4bc19324f20`
- ir bin sha256: `2ac6e241235fd70e110ae90771ffc9ec8ff11de70ab6f17992d574e156654a73`
- log: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\cell_i_compile.log`

```
# command: C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py --ir C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_i --device NPU --mode direct
# started: 2026-04-25T19:49:12Z
# ir xml sha256: 6e662ae7ed0e855460c939d266f52b3b7383e2535a717c2cb13da4bc19324f20
# ir bin sha256: 2ac6e241235fd70e110ae90771ffc9ec8ff11de70ab6f17992d574e156654a73

READY mode=direct device=NPU ir=C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_i
[ERROR] 15:49:14.661 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.embed_tokens/ov_ext::embedding/Convert_1' (type 'Convert'): input '0' bounds are '[9223372036854775807, 9223372036854775807]'
[ERROR] 15:49:14.663 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.embed_tokens/ov_ext::embedding/Gather' (type 'Gather'): input '1' bounds are '[9223372036854775807, 9223372036854775807]'
[ERROR] 15:49:14.663 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::pow/Power' (type 'Power'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
[ERROR] 15:49:14.663 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::mean/ReduceMean' (type 'ReduceMean'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
[ERROR] 15:49:14.663 [vpux-compiler] Got Diagnostic at loc(fused<{name = "__module.model.layers.0.input_layernorm/aten::mul/Multiply", type = "Multiply"}>["__module.model.layers.0.input_layernorm/aten::mul/Multiply"]) : Got non broadcastable dimensions pair : '9223372036854775807' and -9223372036854775808'
loc(fused<{name = "__module.model.layers.0.input_layernorm/aten::mul/Multiply", type = "Multiply"}>["__module.model.layers.0.input_layernorm/aten::mul/Multiply"]): error: Got non broadcastable dimensions pair : '9223372036854775807' and -9223372036854775808'
[ERROR] 15:49:14.664 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::mul/Multiply' (type 'Multiply'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
PYTHON_EXCEPTION:RuntimeError:Exception from src\inference\src\cpp\core.cpp:133: | Exception from src\inference\src\dev\plugin.cpp:58: | Exception from src\plugins\intel_npu\src\plugin\src\plugin.cpp:879: | Exception from src\plugins\intel_npu\src\compiler_adapter\src\ze_graph_ext_wrappers.cpp:405: | L0 pfnCreate2 result: ZE_RESULT_ERROR_INVALID_NULL_POINTER, code 0x78000007 - pointer argument may not be nullptr . [NPU_VCL] Compiler returned msg: | Exception from src\core\src\partial_shape.cpp:266: | to_shape was called on a dynamic shape. |  |  |  |  | 
Traceback (most recent call last):
  File "C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py", line 70, in main
    _cm = core.compile_model(str(xml), args.device, ov_config)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\mrbla\BlarAI\.venv\Lib\site-packages\openvino\_ov_api.py", line 646, in compile_model
    super().compile_model(model, device_name, {} if config is None else config),
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Exception from src\inference\src\cpp\core.cpp:133:
Exception from src\inference\src\dev\plugin.cpp:58:
Exception from src\plugins\intel_npu\src\plugin\src\plugin.cpp:879:
Exception from src\plugins\intel_npu\src\compiler_adapter\src\ze_graph_ext_wrappers.cpp:405:
L0 pfnCreate2 result: ZE_RESULT_ERROR_INVALID_NULL_POINTER, code 0x78000007 - pointer argument may not be nullptr . [NPU_VCL] Compiler returned msg:
Exception from src\core\src\partial_shape.cpp:266:
to_shape was called on a dynamic shape.





FAILED elapsed=2.31s
```

### Cell J1 — Cell B IR, direct compile on NPU with NPU_COMPILER_TYPE=MLIR
- ir: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b`
- ir xml sha256: `467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7`
- ir bin sha256: `0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af`
- log: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\cell_j1_compile.log`

```
# command: C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py --ir C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b --device NPU --mode direct --ov-config NPU_COMPILER_TYPE=MLIR
# started: 2026-04-25T19:49:15Z
# ir xml sha256: 467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7
# ir bin sha256: 0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af

READY mode=direct device=NPU ir=C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b
ov_config={'NPU_COMPILER_TYPE': 'MLIR'}
PYTHON_EXCEPTION:RuntimeError:Exception from src\inference\src\cpp\core.cpp:133: | Exception from src\inference\src\dev\plugin.cpp:58: | Exception from src\plugins\intel_npu\src\al\include\intel_npu/config/options.hpp:835: | Value 'MLIR' is not a valid COMPILER_TYPE option |  |  | 
Traceback (most recent call last):
  File "C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py", line 70, in main
    _cm = core.compile_model(str(xml), args.device, ov_config)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\mrbla\BlarAI\.venv\Lib\site-packages\openvino\_ov_api.py", line 646, in compile_model
    super().compile_model(model, device_name, {} if config is None else config),
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Exception from src\inference\src\cpp\core.cpp:133:
Exception from src\inference\src\dev\plugin.cpp:58:
Exception from src\plugins\intel_npu\src\al\include\intel_npu/config/options.hpp:835:
Value 'MLIR' is not a valid COMPILER_TYPE option



FAILED elapsed=0.41s
```

### Cell J2 — Cell B IR, direct compile on NPU with NPU_COMPILER_TYPE=DRIVER
- ir: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b`
- ir xml sha256: `467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7`
- ir bin sha256: `0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af`
- log: `C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\cell_j2_compile.log`

```
# command: C:\Users\mrbla\BlarAI\.venv\Scripts\python.exe C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py --ir C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b --device NPU --mode direct --ov-config NPU_COMPILER_TYPE=DRIVER
# started: 2026-04-25T19:49:16Z
# ir xml sha256: 467f67b16f9806b0e592125509cbfacffba821948aa317624fcb11877f54b1e7
# ir bin sha256: 0d81347d108386358254ed080cd47ce593f826c39ac896b0d689b4b1d1b187af

READY mode=direct device=NPU ir=C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\exports\cell_b
ov_config={'NPU_COMPILER_TYPE': 'DRIVER'}
[ERROR] 15:49:18.566 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.embed_tokens/ov_ext::embedding/Convert_1' (type 'Convert'): input '0' bounds are '[9223372036854775807, 9223372036854775807]'
[ERROR] 15:49:18.566 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.embed_tokens/ov_ext::embedding/Gather' (type 'Gather'): input '1' bounds are '[9223372036854775807, 9223372036854775807]'
[ERROR] 15:49:18.566 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::pow/Power' (type 'Power'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
[ERROR] 15:49:18.566 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::mean/ReduceMean' (type 'ReduceMean'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
[ERROR] 15:49:18.566 [vpux-compiler] Got Diagnostic at loc(fused<{name = "__module.model.layers.0.input_layernorm/aten::mul/Multiply", type = "Multiply"}>["__module.model.layers.0.input_layernorm/aten::mul/Multiply"]) : Got non broadcastable dimensions pair : '9223372036854775807' and -9223372036854775808'
loc(fused<{name = "__module.model.layers.0.input_layernorm/aten::mul/Multiply", type = "Multiply"}>["__module.model.layers.0.input_layernorm/aten::mul/Multiply"]): error: Got non broadcastable dimensions pair : '9223372036854775807' and -9223372036854775808'
[ERROR] 15:49:18.567 [IE::FrontEnd::importNetwork]   Upper bounds are not specified for node '__module.model.layers.0.input_layernorm/aten::mul/Multiply' (type 'Multiply'): input '0' bounds are '[9223372036854775807, 9223372036854775807, 1024]'
PYTHON_EXCEPTION:RuntimeError:Exception from src\inference\src\cpp\core.cpp:133: | Exception from src\inference\src\dev\plugin.cpp:58: | Exception from src\plugins\intel_npu\src\plugin\src\plugin.cpp:879: | Exception from src\plugins\intel_npu\src\compiler_adapter\src\ze_graph_ext_wrappers.cpp:405: | L0 pfnCreate2 result: ZE_RESULT_ERROR_INVALID_NULL_POINTER, code 0x78000007 - pointer argument may not be nullptr . [NPU_VCL] Compiler returned msg: | Exception from src\core\src\partial_shape.cpp:266: | to_shape was called on a dynamic shape. |  |  |  |  | 
Traceback (most recent call last):
  File "C:\Users\mrbla\BlarAI\phase2_gates\evidence\issue34450\repro_compile.py", line 70, in main
    _cm = core.compile_model(str(xml), args.device, ov_config)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\mrbla\BlarAI\.venv\Lib\site-packages\openvino\_ov_api.py", line 646, in compile_model
    super().compile_model(model, device_name, {} if config is None else config),
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
RuntimeError: Exception from src\inference\src\cpp\core.cpp:133:
Exception from src\inference\src\dev\plugin.cpp:58:
Exception from src\plugins\intel_npu\src\plugin\src\plugin.cpp:879:
Exception from src\plugins\intel_npu\src\compiler_adapter\src\ze_graph_ext_wrappers.cpp:405:
L0 pfnCreate2 result: ZE_RESULT_ERROR_INVALID_NULL_POINTER, code 0x78000007 - pointer argument may not be nullptr . [NPU_VCL] Compiler returned msg:
Exception from src\core\src\partial_shape.cpp:266:
to_shape was called on a dynamic shape.





FAILED elapsed=2.34s
```
