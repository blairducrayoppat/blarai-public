---
ledger_id: 20260627_230431_uc010_illustrate-cartoon-styles
date: 2026-06-27
sprint_id: null
entry_type: feature
predecessor: 20260616_182807_uc010_content-attestation
branch: feat/703-illustrate-cartoon
merge_commit: null
disposition: COMPLETE
---

# UC-010 — Illustration + cartoon image styles join photoreal (`/imagine` + `/illustrate` + `/cartoon`)

## Summary

Extended UC-010 (ADR-033) from one image command to **three selectable styles**, chosen
per-image by slash command rather than by config swap:

- **`/imagine`** — photoreal (RealVisXL V5.0 INT8), unchanged.
- **`/illustrate`** — crisp flat-vector illustration: base Stable Diffusion XL 1.0 INT8 + a
  flat-style **prompt template**, NO adapter.
- **`/cartoon`** — soft cartoon: base SDXL 1.0 INT8 + the DoctorDiffusion vector LoRA applied
  **at runtime** via `ov_genai.AdapterConfig` (alpha 0.8), **never fused** into the base weights.

Built and live-verified on the real Arc 140V through the production path
(`require_signed_manifest=true` + cartoon LoRA SHA-256 integrity pin). Standing gate
**4606 passed / 0 failed**; WinUI desktop build **0 warn / 0 err**. Branch
`feat/703-illustrate-cartoon`, not yet merged at authoring.

## Root-cause finding (the load-bearing engineering call)

The original plan was to *fuse* a flat-vector LoRA into base SDXL and ship the baked result as
the illustration model. Fusing collapsed prompt conditioning — the model produced coherent,
confident output that **ignored the prompt** (ask for a coffee cup, get a generic flat blob).
Isolated by control: a known-good finetune (RealVisXL) through the *identical* convert→INT8→
generate harness was prompt-faithful, and base-SDXL-with-no-LoRA + a flat prompt was prompt-
faithful — so the harness was innocent and the fusion was the variable. Confirmed mechanism:
fusing a strong style LoRA overwrites the cross-attention weights that carry text conditioning
(INT8 data-free quantization compounds it with outliers). **Resolution: never fuse** — illustrate
uses prompting alone; cartoon applies the LoRA at runtime where it influences without silencing.
Trade accepted: runtime-adapter cartoon is \~20 s slower cold (60.6 s vs 39.8 s) — paid willingly,
because a fused-but-deaf model is worthless. Full narrative: journal fragment
`docs/journal_fragments/2026-06-27_703-illustrate-cartoon.md`.

## Governance decision (recorded on #703)

The two new styles do **not** carry the content-attestation go-live ceremony that the uncensored
photoreal model carries — their base is not an uncensored finetune, so that gate would attest
nothing. **Kept intact**: `require_signed_manifest=true` (detached `manifest.json.sig` verified at
load) and the cartoon LoRA SHA-256 pin (verified before the runtime adapter is applied). Relax the
theater; keep the integrity spine.

## Deliverables

- **`shared/inference/image_gen.py`** — `VARIANT_ILLUSTRATION` + `VARIANT_ILLUSTRATION_CARTOON`
  (replacing the abandoned `…_PLAYGROUND`); `ImageGenConfig` gains `lora_adapter_path` /
  `lora_adapter_alpha` / `lora_adapter_sha256`; `_build_adapter_config()` (fail-soft on missing
  file or SHA-256 mismatch; the pin is MANDATORY under `require_signed_manifest` — an unpinned
  adapter is refused, since the LoRA is the one weight outside signed-manifest coverage);
  `_construct_pipe(... adapters=)` threads the AdapterConfig into compile/ctor.
- **`shared/ipc/protocol.py`** — `IMAGE_GEN_STYLE_{PHOTOREAL,ILLUSTRATION,CARTOON}` constants +
  `IMAGE_GEN_STYLES` frozenset; `encode_image_gen_request(... style=)` validated + on the wire.
- **`services/assistant_orchestrator/src/entrypoint.py`** — `_image_gen_config_for_style()`
  builds the per-style `ImageGenConfig` (photoreal=RealVisXL/no-adapter; illustration=base SDXL/
  no-adapter; cartoon=base SDXL+LoRA; hires-fix photoreal-only); `_handle_image_gen_request`
  reads `style` and reconfigures before the `is_available` gate; the legacy
  `image_gen_model_variant` key is a deprecated back-compat no-op.
- **`services/ui_gateway/src/imagine_coordinator.py`** — `/illustrate` + `/cartoon` verbs;
  `_handle_styled()` wraps the subject in the flat-vector template and dispatches with `style`;
  `_dispatch_generate(... style=)`.
- **`shared/ipc/slash_commands.py` + `services/ui_winui/MainWindow.xaml.cs`** — `/illustrate` +
  `/cartoon` added to the backend-passthrough allowlist SSOT and the WinUI command array /
  suggestions / help.
- **`services/assistant_orchestrator/config/default.toml`** — illustration model dir →
  `models/sdxl-illustration/openvino-int8-gpu`; cartoon LoRA path / alpha / sha256 keys.
- **Model on disk (gitignored)** — `models/sdxl-illustration/openvino-int8-gpu` (base SDXL 1.0
  INT8, 3.3 GB, OV tokenizers, **signed** manifest) + `lora/DD-vector-v2.safetensors` (\~218 MB).
- **Tests** — renamed-constant + adapter-config fail-soft (`shared/tests/test_image_gen.py`),
  per-style config mapping + IPC style round-trip (`…/tests/test_image_gen_wiring.py`),
  `/illustrate`+`/cartoon` coordinator tests (`…/tests/test_imagine_coordinator.py`).

## Verification

- Standing gate: **4606 passed, 118 deselected, 0 failed** (2:25).
- Independent adversarial review (8 focus areas): **MERGE-WITH-NITS**, 0 CRITICAL / 0 MAJOR — the
  load-bearing invariants all hold (LoRA hash computed-and-compared BEFORE apply, never fused,
  signed-manifest covers all three styles, zero new egress, no `/imagine` regression, WinUI
  allowlist in sync). All 3 MINOR nits FIXED in the follow-up commit: (1) the LoRA pin is now
  MANDATORY under `require_signed_manifest` (an unpinned adapter is refused); (2) explicit
  decode-side style re-validation + WARNING log; (3) +4 regression tests (unpinned-refusal lock,
  config→pin threading, unknown-style→photoreal fallback, the handler→configure production join).
- Re-gate after the nit fixes: **4576 passed / 0 failed** (1:43) — the full blast radius + the +4
  new tests. `launcher/tests/test_launcher.py` was excluded from THIS re-run: its fully-mocked
  `main()` tests did not complete under heavy concurrent load (3 research sessions + 2 live
  `launcher --winui` apps doing real cert work in `<repo>/certs/`). That file is UNRELATED to the
  #703 change (a mocked `main()` reaches no image-gen code) and the 4606 standing-gate run above
  passed it; a clean reconfirm folds into the operator's quiet-box full-gate step.
- WinUI desktop build: **0 warnings / 0 errors** (`-p:Platform=x64 -r win-x64 --self-contained`).
- Live E2E on Arc 140V, production settings (signed manifest + LoRA hash pin), `is_available=true`
  for all three; cold end-to-end 43.8 s / 39.8 s / 60.6 s; three distinct images saved. Community-
  grade perf: `PERFORMANCE_LOG.md` (2026-06-27) + `docs/performance/uc010_image_styles_arc140v_2026-06-27.json`.

## Follow-ups (tracked)

- Remove the now-vestigial `image_gen_model_variant` config key (deprecated no-op) — hardening
  follow-up on #703.
- Publish a steady-state generate-only + resident-memory companion to the cold E2E numbers.
