---
ledger_id: 20260616_161934_uc010_local-generative-imaging
date: 2026-06-16
sprint_id: null
entry_type: EA
predecessor: 20260512_144000_sprint11_ea3_swagr-cross-repo-template
branch: 666-uc010-image-gen
merge_commit: null
disposition: COMPLETE
---

# UC-010 — Local Generative Imaging (text→image + image+text→image), built DORMANT

## Summary

Built UC-010 (ADR-033) — local image generation on the Arc 140V via OpenVINO GenAI,
in two modes (text→image + image-conditioned img2img), with an uncensored SDXL INT8
finetune (RealVisXL V5.0). Worktree-isolated build on `666-uc010-image-gen`, shipped
DORMANT, NOT merged — handed back for Guide review. UC-010 deliberately EXPANDS the
canonical 9-Use-Case vision at the Lead Architect's direction (image generation was
an "honest future track" in ADR-015 / journal §19).

The Phase-0 memory spike (build-or-no-build gate) PASSED on the real Arc 140V before
the build: 14B core + \~3k KV-cache + SDXL INT8 co-resident + a 1024² generate peaked
\~26.0 GB vs the 31.323 GB ceiling (5.3 GB headroom); SDXL load 18.7 s; 1024² generate
10.7 s. The budget closes with the 14B held resident, so the "14B never evicted"
invariant holds and the build proceeded.

## Deliverables

- **`shared/inference/image_gen.py` (NEW)** — structural clone of `vlm.py`:
  load-on-demand + Fail-Soft + `unload()` + `log_memory` brackets, a `_model_kind`
  global (one diffusion pipeline resident; kind-swap unloads the prior),
  `Text2ImagePipeline`/`Image2ImagePipeline`, GPU props minus `MODEL_PRIORITY=HIGH`,
  config-injected dormancy gate, dimension-clamp circuit breaker, fail-closed weight
  verify at load.
- **`services/ui_gateway/src/imagine_coordinator.py` (NEW)** — `/imagine`, `/edit`
  (LOCAL file or `blarai-img://` seed — NEVER a URL; reuses the ingest UNC/containment/
  extension guards), `/save` (TUI fallback); injected transport so unit-testable with
  no AO/model.
- **`services/ui_gateway/src/generated_image_resolver.py` (NEW)** — host-side
  `blarai-img://` → `(mime, bytes)` resolver reading `generated_images` (then
  `knowledge_images` fallback), anchored full-string id gate.
- **`generated_images` table + `store_generated_image`/`get_generated_image`/
  `delete_generated_image`** in `knowledge_bank.py` — born-encrypted (SAME DEK,
  AAD-bound `session_id|image_id`), DELETE-on-discard, never embedded.
- **`IMAGE_GEN_REQUEST`/`IMAGE_GEN_RESULT`** MessageType + encode/decode on
  `shared/ipc/protocol.py`; the AO `_handle_image_gen_request` handler + the
  eviction→generate→store→unload orchestration in `entrypoint.py`.
- **`generate_image`** in `tools._REGISTRY` (`RiskTier.GUARDED`) + `pgov.TOOL_CALL_ALLOWLIST`;
  the system-prompt tool-use block updated (4→5 tools).
- **`[image_generation]`** config block + `ResolvedConfig` fields/property/validator.
- **`verify_all_manifest_entries_nested`** in `weight_integrity.py` — a sibling of the
  flat sweep for the nested diffusers-OV `.bin` layout (the flat function globs `*.bin`
  flat and collides on the repeated bare name; the locked flat function is untouched).
- **Governance:** ADR-033 (PROPOSED, built dormant); DECISION_REGISTER row + range bump
  (ADR-005..ADR-033); UC-010 in `Use Cases_FINAL.md`; journal fragment
  `2026-06-16_local-image-gen.md`; PERFORMANCE_LOG + `docs/performance/` JSON Phase-0
  numbers.

## Quality Gate

Standing gate (`pytest shared/ services/ launcher/ tests/integration/ tests/security/
-m "not hardware and not winui and not slow"`, LOCALAPPDATA-redirected):
**3669 passed, 0 failed, 20 skipped, 118 deselected** — +36 over the 3633 baseline
(the 20 skips are the pre-existing `semantic_router` worktree env-skips; the gitignored
bge model is absent here — benign, passes on main). +56 new tests (54 unit + 2 @hardware
deselected). Egress invariants intact — "exactly one runtime module imports a network
client" still passes (UC-010 adds NO network surface).

## Dormancy (test-proven)

`[image_generation].enabled=false` ships AND the model is gitignored (absent) ⇒
`image_gen.is_available()` False, `/imagine` + `generate_image` degrade to a clear
notice with NO load attempted. `generate_image` is GUARDED; the PA allows a local
`tool:generate_image` CAR with NO adjudication-logic change (the go-live "lift the
purpose-deny" is the `enabled` flip + model presence — a config/registration step,
BED-1-style). Go-live is a SEPARATE LA-present ceremony (one-time operator content
attestation → flip → live GPU verify).

## Deviations / escalations

- **`verify_all_manifest_entries_nested` added (deviation-of-necessity):** the plan
  said "verify via `weight_integrity.py` `verify_all_manifest_entries`", but that flat
  function cannot handle the nested diffusers-OV layout (subdir `.bin` files, repeated
  bare names). Added a clearly-named sibling reusing the proven primitives; the locked
  flat function is untouched. Surfaced in the hand-back.
- **No genuine capability/posture decision was left unsettled** — the plan settled the
  model, content-safety posture, tier, and dormancy; this is a faithful execution.
- **`blarai-img://` `/edit`-seed + `/save` bank-reader bridge** (the gateway reaching
  the AO's `generated_images` store across IPC) is left as the one wiring step for
  those two display-path features; text2image + local-file `/edit` work without it.
  Named as a go-live successor, not a defect.
