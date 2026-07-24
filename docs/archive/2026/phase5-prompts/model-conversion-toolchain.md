---
title: model-conversion-toolchain
status: archived
area: portfolio
---

# Model Conversion Toolchain (OpenVINO IR export)

*Status: sanctioned path. Verified working 2026-07-15 (ticket #541).*
*Home: `docs/` — this is toolchain-hygiene guidance for converting models to OpenVINO IR.*

## Summary (read this first)

BlarAI needs Hugging Face models converted to OpenVINO Intermediate Representation
(IR — the `.xml` + `.bin` format the runtime loads). There are two supported ways to
get a converted model, in priority order:

1. **Default / routine path — pre-converted IR from the Hugging Face hub.** When an
   official `OpenVINO/...-int4-ov` (or similar) build exists, download it directly. No
   local conversion, no toolchain risk. This is how the production models (Qwen3-14B,
   the draft, Whisper, etc.) were obtained.
2. **Local conversion — `.export-venv` + `optimum-cli export openvino`.** Use this only
   when no pre-converted IR exists (a new model, a custom finetune, or upstream
   contribution work). This is the **sanctioned conversion surface**; do not convert in
   any other environment.

## Hard rule: never convert in the runtime `.venv`

The runtime `.venv` runs the live 14B inference stack (openvino-genai), the
sentence-transformers embedder, and the app services. Its dependency pins are
load-bearing. **Never `pip install` conversion toolchains (transformers/optimum/
optimum-intel/nncf/torch) into it, and never re-pin it to satisfy a conversion need.**
Conversion lives in a *separate* venv. This is the toolchain-hygiene rule from CLAUDE.md
(build/conversion toolchains in a SEPARATE venv, never the runtime `.venv`).

## The sanctioned conversion environment: `.export-venv`

Location: `C:/Users/mrbla/BlarAI/.export-venv` (gitignored).

Verified-working stack (2026-07-15, ticket #541 T0):

| Package             | Version        |
|---------------------|----------------|
| python              | 3.11.9         |
| transformers        | 4.51.3         |
| optimum             | 2.1.0          |
| optimum-intel       | 1.27.0 (editable — see below) |
| optimum-onnx        | 0.1.0          |
| openvino            | 2026.0.0       |
| openvino-tokenizers | 2026.0.0.0     |
| torch               | 2.6.0+cpu      |
| nncf                | 3.0.0          |

`optimum-intel` is installed **editable** from the upstream-contributor checkout at
`C:/Users/mrbla/BlarAI/optimum-intel`:

- remote: `rkazants/optimum-intel`
- branch: `support_qwen3_5`
- **enshrined SHA: `d8864c45db718f09ac312120502c1340229dc505`**

Rebuild the venv against this SHA if it is ever lost. Advancing the SHA is an explicit
choice made during an upstream-contribution session, not a routine update.

## Usage

```
.export-venv/Scripts/optimum-cli export openvino \
  --model <hf-model-id-or-local-path> \
  --task text-generation \
  <output-dir>
```

Produces `openvino_model.xml` + `openvino_model.bin` (+ tokenizer/detokenizer IR).
Add `--weight-format int4` (or `int8`) for quantized export.

## Why this doc exists (the #541 history)

The runtime `.venv` at one point carried a *dev-build* triad
(transformers 5.x / optimum `2.1.0.dev0` / optimum-intel `1.27.0.dev0`) where
`optimum.exporters.openvino` failed to import:
`cannot import name '_CAN_RECORD_REGISTRY' from 'transformers.utils.generic'`.
That was a bleeding-edge dev-build coupling. The runtime was never affected (nothing in
`services/`, `shared/`, or `launcher/` imports optimum at runtime — the 14B path uses
openvino-genai directly), so the fix was never to disturb the runtime.

The released triad in `.export-venv` does not have this coupling: `_CAN_RECORD_REGISTRY`
is still absent from transformers 4.51.3, but released optimum 2.1.0 does not reference
it, so `import optimum.exporters.openvino` succeeds and a full end-to-end export produces
valid IR (verified 2026-07-15).

## Verification (re-run to re-sanction after any change)

```
.export-venv/Scripts/python -c "import optimum.exporters.openvino; print('OK')"
.export-venv/Scripts/optimum-cli export openvino \
  --model hf-internal-testing/tiny-random-gpt2 --task text-generation <tmp-out>
# expect: openvino_model.xml/.bin produced, no errors
```
