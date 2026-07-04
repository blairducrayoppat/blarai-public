# UC-010 Image-Generation Go-Live Runbook

**Staging → signing → attesting → flipping → live-verify.** ADR-033. For the
Lead Architect (non-developer-friendly). This is the SEPARATE, LA-present
ceremony that takes UC-010 Local Generative Imaging from DORMANT to live. It is
the ONLY thing that flips `[image_generation].enabled`. Reuses the
`BlarAI-Manifest-Signing` TPM key from the manifest signing ceremony
(`docs/runbooks/manifest_signing_ceremony.md`).

> **What this ceremony makes live:** local text→image + image+text→image on the
> Arc 140V, zero egress, plus the inline display of generated images in the WinUI
> window (the WS3 render corridor's live-pixel confirm). It does NOT open any
> network door — UC-010 adds no network client.

## Preconditions (verify BEFORE starting)

1. The uncensored SDXL diffusers-OV INT8 model is present on the box at
   `models/sdxl-uncensored/openvino-int8-gpu/` (the diffusers-OV layout: `unet/`,
   `vae_decoder/`, `vae_encoder/`, `text_encoder*/`, `tokenizer*/`, `scheduler/`,
   `model_index.json`). `models/` is gitignored — the capability ships ABSENT, so
   this is a provisioning step done on the box.
2. The Phase-0 memory gate is PASSED (recorded — \~26.0 GB co-resident peak vs the
   31.323 GB ceiling, 5.3 GB headroom). If the model checkpoint changed since,
   re-run the Phase-0 spike first.
3. A TPM 2.0 / Windows CNG provider is available (the `BlarAI-Manifest-Signing`
   key must already be provisioned — see `manifest_signing_ceremony.md`; if not,
   provision it first with `C:/Users/mrbla/blarai/.venv/Scripts/python.exe -m shared.security.provision_manifest_signing_key`).
4. `[image_generation].require_signed_manifest = true` and `enabled = false` in
   `services/assistant_orchestrator/config/default.toml` (the shipped defaults).

> **INTERPRETER — run every Python command below with the project venv, NOT the bare `python`.**
> The dev box's system `python` is **3.14 and lacks `cryptography`**, so the sign / verify / provision
> steps fail with `ModuleNotFoundError: No module named 'cryptography'` (the stager at Step 1 is the only
> one that happens to work on bare Python, because it is hashlib-only). Use
> `C:/Users/mrbla/blarai/.venv/Scripts/python.exe` (Python 3.11.9, the full dependency set). The commands
> below are written with the full venv path so they copy-paste directly.
>
> **Run every command from the repo root `C:\Users\mrbla\BlarAI`.** All paths (and the `shared.*`
> imports) are relative to it — from any other directory the stager reports `model directory not found`
> and the `python -c "from shared..."` commands fail with `No module named 'shared'`. `cd` there first.

## Step 1 — Stage the NESTED SDXL weight manifest

This hashes every nested `.bin` weight AND every OpenVINO `.xml` topology file AND
`model_index.json` (so a swapped compute graph cannot pass the check), keyed by
relative path — exactly what `verify_all_manifest_entries_nested` requires.

```powershell
$env:BLARAI_MODEL_DIR     = "models/sdxl-uncensored/openvino-int8-gpu"
$env:BLARAI_MANIFEST_PATH = "models/sdxl-uncensored/openvino-int8-gpu/manifest.json"
C:/Users/mrbla/blarai/.venv/Scripts/python.exe -m shared.models.stage_production_manifest --nested
```

Expect "Nested Manifest Staged Successfully" and a count of `.bin` + `.xml` +
`model_index.json` entries. (Do NOT use the bare/flat invocation — that stages the
14B `.bin`-only layout.)

## Step 2 — SIGN the manifest (TPM)

The stager deliberately does NOT sign. Sign the just-staged manifest with the
TPM key so the load's `require_signed_manifest=true` gate passes:

```powershell
C:/Users/mrbla/blarai/.venv/Scripts/python.exe -c "from shared.models.manifest_signer import sign_manifest; print(sign_manifest('models/sdxl-uncensored/openvino-int8-gpu/manifest.json'))"
```

This writes `manifest.json.sig` (+ `manifest.json.pub`) alongside the manifest.
Confirm the nested verify passes signed:

```powershell
C:/Users/mrbla/blarai/.venv/Scripts/python.exe -c "from shared.models.weight_integrity import verify_all_manifest_entries_nested as v; r=v('models/sdxl-uncensored/openvino-int8-gpu','models/sdxl-uncensored/openvino-int8-gpu/manifest.json', require_signed=True); print('VERIFIED' if r.all_verified else ('REFUSED: '+str(r.error)))"
```

Expect `VERIFIED`. (A REFUSED here means the manifest, a weight, an `.xml`, or
`model_index.json` does not match, or the `.sig` is missing/invalid — STOP and
investigate; do not proceed.)

## Step 3 — One-time operator CONTENT ATTESTATION (LA, on the record)

Content safety for UC-010 is **governance + this one-time attestation, NOT a
classifier** (ADR-033 §content-safety): the model is uncensored for all *legal*
content; the immovable legal boundary is the operator's sole documented
responsibility and a deliberate ACCEPTED-RISK. Record the attestation in the
ledger (`docs/ledger/`) + the build journal before the flip. This is an
LA-present, on-the-record step — it cannot be automated away.

## Step 4 — Flip the weld lock

With the manifest staged + signed + verified and the attestation recorded, flip
the master weld lock (the Orchestrator edits config; the LA is present for this
irreversible-in-spirit step):

- `services/assistant_orchestrator/config/default.toml` →
  `[image_generation] enabled = true` (leave `require_signed_manifest = true`).

`is_available()` now returns True iff the model is present AND `openvino_genai`
imports. No adjudication rule changes — `generate_image` stays `GUARDED` and the
local `tool:generate_image` CAR passes the existing PA rules (the "lift the
purpose-deny" is this `enabled` flip + model presence, not a rule change).

## Step 5 — LIVE GPU verify (on the Arc 140V — inherently on-hardware)

Run the deselected `@hardware` go-live tests + the live-pixel confirms:

```powershell
$env:LOCALAPPDATA = (New-Item -ItemType Directory -Force "$env:TEMP\blarai_golive_la").FullName
C:/Users/mrbla/blarai/.venv/Scripts/python.exe -m pytest -m hardware shared/tests/test_image_gen.py -v
```

Then, with the AO running and the WinUI window open, confirm by eye + by scan:

1. **text→image:** `/imagine <prompt>` produces a real image; it renders inline
   in the WinUI window (the WS3 `ImageResolver.ResolveAsync` live-pixel path — the
   decrypt corridor's first real round-trip: WinUI → pipe → dispatcher
   `resolve_image` → vsock → AO decrypt → bytes → `BitmapImage`).
2. **image+text→image:** `/edit <blarai-img://id-or-local-file> <prompt>` produces
   an edited image and renders it.
3. **born-encrypted at rest:** confirm the `generated_images` row's `data`/`prompt`
   columns are ciphertext (no plaintext pixels/prompt on disk); a raw scan of
   `knowledge.db` finds no plaintext PNG header for the generated image.
4. **DELETE-on-discard zeroing:** discard a generated image, checkpoint, and
   confirm `PRAGMA secure_delete` is `1` and no residual ciphertext lingers in the
   freed pages (the SE-1 posture, now live).
5. **`/save`:** `/save <id> <local-path>` writes the decrypted PNG to a LOCAL path;
   a UNC/network destination is refused.
6. **eviction:** confirm the diffusion pipeline is evicted after each generate and
   the 14B is never evicted (memory deltas in `PERFORMANCE_LOG.md`).

Record the live numbers (load/generate latency, co-resident peak) — community-grade
— in `PERFORMANCE_LOG.md` + `docs/performance/`.

## Step 6 — Journal + ledger (same day)

Write the go-live BUILD_JOURNAL entry (the arc + the live measurements + the
attestation reference) and the ledger entry. Update the CLAUDE.md Active-State
test baseline if the @hardware count moved.

## Out of scope (separate events)

- **UC-003 article-image DISPLAY go-live (Phase 2):** the off-site consent prompt
  UI + the binary-image egress door opening (a network/air-gap governance event).
  The WS3 render corridor built here already serves it once that door opens.
- The DNS-rebinding / TOCTOU transport hardening (a tracked egress residual).
