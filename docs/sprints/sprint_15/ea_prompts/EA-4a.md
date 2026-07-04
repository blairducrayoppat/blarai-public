# EA-4a — Ceremony Helper Tooling (novice-safe CLIs for the EA-4 on-chip ceremony)

> Sprint 15. Size: **S/M**. Depends on: EA-1/2/3 merged. Branch off **current `main`** (`3b59965`+). Worktree-isolated; same independent merge-gate. **Prerequisite for the EA-4 ceremony runbook** — the LA is a non-developer, so every ceremony step must be a single copy-paste command with clear output (never hand-typed Python or hashes). **Status: DRAFT.**

## Why

The EA-4 ceremony is the LA's on-chip session, and the LA is a **non-developer**. Two ceremony steps have **no novice-runnable command** today: (1) confirming which TPM keys / keystore are present, and (2) computing the real model SHA-256 + staging the real-digest Known-Good Manifest. EA-4a adds two small, safe CLIs so each step is one clear command. (JWT-key provisioning already has `provision_signing_key`; the boots are `python -m launcher`.)

## Role

code-specialist, isolated worktree, BlarAI runtime (NO external network, NO new dependencies, fail-closed), strict type hints, PEP 8.

## In-scope (deliverables)

1. **Ceremony preflight check** — `shared/security/ceremony_preflight.py`, runnable `python -m shared.security.ceremony_preflight`. **READ-ONLY (no mutation, never creates/mutates a key).** Reports a clear ✓/✗ checklist a non-developer can read:
   - TPM availability (`tpm_signer.is_available()` / `tpm_sealer.is_available()`) — if unavailable, say so clearly (the ceremony must run on the deployment hardware).
   - DEK seal key present (`tpm_sealer.key_exists("BlarAI-DEKSeal")`)
   - Audit signing key present (`tpm_signer.key_exists("BlarAI-Audit-Signing-Key-v1")`)
   - JWT signing key present (`tpm_signer.key_exists("BlarAI-PA-JWT-Signing")`)
   - DEK keystore file present (the `BLARAI_DEK_KEYSTORE` path / default keystore)
   - `certs/pa_public.pem` present (the JWT public anchor)
   - Production Known-Good Manifest present + its digest matches the real model (reuse `shared/models/weight_integrity.compute_sha256` if the model file exists; else report "model not found — run the manifest stager / check the path")
   Output: a human-readable checklist + a one-line bottom-line ("READY for production boot" / "NOT READY — missing: …"). Crystal-clear wording for a non-developer.
2. **Production manifest stager** — `shared/models/stage_production_manifest.py`, runnable `python -m shared.models.stage_production_manifest`. Computes the real SHA-256 of the production model binary file(s) in the configured model dir (reuse `weight_integrity.compute_sha256`) and writes the **real-digest** Known-Good Manifest at the configured path (`default.toml` `inference.weight_manifest`). Idempotent; clear output ("computed <digest> for openvino_model.bin; wrote manifest to <path>"); fail-closed (model file missing → clear error, no partial write). **Does NOT sign** the manifest (`require_signed_manifest` stays false; FUT-04 signing is #106 — out of scope).
3. **Gitignore-per-machine the production manifest** — the real-digest manifest is a per-machine artifact (tied to the LA's model file), like `pa_public.pem` / `ca.pem`. `git rm --cached models/qwen3-14b/openvino-int4-gpu/manifest.json` (untrack; keep on disk), add it to `.gitignore`, and keep a **committed template** (`manifest.json.example`) documenting the structure (the EA-3 `_stub_notice` stub is a fine template). **Constraint:** confirm no test depends on the committed manifest being *tracked* (EA-3's harness uses per-test `tmp_path` manifests — verify); if any does, point it at the template or a tmp fixture. The stager writes the real (gitignored) `manifest.json`.
4. **Tests** for both CLIs (no real TPM/model needed — mock `key_exists`/`is_available`, use a temp model file + temp manifest path; inherit the root `conftest.py` isolation). + journal fragment.

## Out-of-scope

- The **activation flip** (the Orchestrator makes the one-liner at ceremony time).
- FUT-04 manifest **signing** (#106).
- Running the ceremony / provisioning real keys (that is the LA's on-chip EA-4).
- The runbook itself (the Orchestrator writes it once these helpers land).

## Safety

- No external network, no new dependencies, fail-closed. The preflight is **READ-ONLY** (never creates/mutates a key). The stager writes only the manifest file (no key/secret handling). NEVER print/log secret material.
- Test isolation (standing rule): venv `C:/Users/mrbla/blarai/.venv/Scripts/python.exe -m pytest`; root `conftest.py` isolation; no real keystore/data touched.

## Acceptance criteria

- Both CLIs run and produce **clear, novice-readable** output; tests green; the production manifest is gitignored-per-machine with a committed template; **no test depends on the tracked manifest**; full suite green, no regressions.

## Process

- **Pre-build comprehension gate (FIRST):** recite the two CLI command names, the manifest untrack/template approach, and confirm no test depends on the tracked manifest — before building. STOP and report if any test does depend on it (so we decide the fix together).
- Branch off **current `main`** (`3b59965`+), isolated worktree, atomic commits.
- Journal fragment `docs/journal_fragments/2026-06-06_s15-ea4a-ceremony-helpers.md`.
- **Return in the merge-gate summary the EXACT console output of both CLIs** (run them against mocks/temp fixtures and paste what they print) — the Orchestrator needs the real output text to write an accurate novice runbook.
