# Weight Integrity Verification Governance

> **Acronyms on first use.** SHA-256 = Secure Hash Algorithm, 256-bit.
> TPM = Trusted Platform Module. ECDSA = Elliptic Curve Digital Signature
> Algorithm. CNG = Cryptography Next Generation (the Windows crypto API).
> PA = Policy Agent. AO = Assistant Orchestrator. KGM = Known-Good Manifest.
> UC = Use Case. ADR = Architecture Decision Record. LA = Lead Architect.
> AIGP = Artificial-Intelligence Governance Professional (the certification
> this record supports).

## Audience

**Primary**: auditor — reviews the fail-closed boundary that ties the Policy
Agent's authority to the bytes of the model it is running. Reads for the exact
mechanism, its coverage, and its declined scope.

**Secondary**: operator — runs the signing ceremony and reads the boot log to
confirm a clean, signature-verified start. Incident responder — follows §5 when
a boot hard-locks or an adjudication fails closed on an integrity mismatch.
Developer — reads §1–§3 for the contract any change to the load or adjudication
path must preserve.

## Prerequisites

- [ADR-011](../adrs/ADR-011-All-LLM-Inference-GPU-NPU-Retirement.md) — all LLM
  inference on the GPU; the resident 14-billion-parameter model that the
  integrity check protects is loaded per this ADR.
- [ADR-012](../adrs/ADR-012-Qwen3-14B-Model-Selection-Speculative-Decoding.md) — Qwen3-14B as
  the unified model + Qwen3-0.6B speculative-decoding draft. Names the weight
  files under integrity coverage.
- [ADR-018](../adrs/ADR-018-TPM-Trust-Root-SGX-Replacement.md) — the TPM
  trust-root primitive. FUT-04 (the manifest-signing capability documented here)
  is scoped by this ADR.
- [ADR-028](../adrs/ADR-028-Measured-Boot-Attestation-Scope.md) — measured-boot
  attestation **scope**. Amendment 1 (2026-06-10) records that production keys
  are **not** Platform-Configuration-Register-bound. This is the on-disk anchor
  for the declined scope in §7.
- [ADR-033](../adrs/ADR-033-Local-Generative-Imaging.md) — UC-010 local image
  generation; the nested-layout Stable Diffusion XL manifests in §4 are governed
  here.
- Peer governance docs:
  [deployment-verification.md](deployment-verification.md) (the boot/activation
  flow this check sits inside),
  [configuration-management.md](configuration-management.md) (the
  `require_signed_manifest` config surface).

## Source References

| Artifact | Path | Notes |
|---|---|---|
| SHA-256 + manifest verification core | `shared/models/weight_integrity.py` | `compute_sha256`, `load_manifest_verified`, `verify_weight_integrity`, `verify_all_manifest_entries`, `verify_all_manifest_entries_nested` |
| TPM signature over the manifest | `shared/models/manifest_signer.py` | `sign_manifest` (ceremony side), `verify_manifest_signature` (boot + re-hash side) |
| TPM primitive (non-exportable ECDSA P-256) | `shared/security/tpm_signer.py` | Microsoft Platform Crypto Provider via `ncrypt.dll`; sign / verify / export-public |
| Boot cascade + weight gate | `services/policy_agent/src/boot.py`, `services/policy_agent/src/entrypoint.py` | measured-boot state machine; `_phase_weight_integrity` / `_verify_weight_integrity_gate` / `_validate_security_material` |
| Load-time full sweep | `services/policy_agent/src/gpu_inference.py`, `services/assistant_orchestrator/src/gpu_inference.py`, `shared/inference/shared_pipeline.py` | `verify_all_manifest_entries` at `load_model()`; target + draft in the shared pipeline |
| Per-adjudication re-verify | `services/policy_agent/src/adjudicator.py` | Stage-2 event-triggered re-hash, fail-closed DENY |
| Config flag | `services/policy_agent/config/default.toml`, `services/assistant_orchestrator/config/default.toml` | `[security].require_signed_manifest`, `[image_generation].require_signed_manifest` |
| Provisioning / signing ceremony | `docs/runbooks/manifest_signing_ceremony.md`, `shared/models/stage_production_manifest.py`, `shared/security/provision_manifest_signing_key.py`, `shared/security/ceremony_preflight.py` | operator-run, LA-present |
| On-disk manifests + signatures | `models/<model>/<precision>/manifest.json`, `manifest.json.sig`, `manifest.json.pub` | weight `.bin` files are gitignored; manifest/`.sig`/`.pub` verified on the operator's checkout |

## Governance Content

### 1. Purpose — why weight integrity is foundational to Policy-Agent trust

The Policy Agent is the single adjudication door: every risky action in BlarAI is
allowed or denied by a classification the PA produces from the resident model's
weights. If those weights can be silently swapped between boots, or in place at
runtime, the adjudicator's verdicts become attacker-chosen while every other
control (deny-by-default egress, born-encrypted storage, the audit chain)
continues to trust them. Weight integrity is therefore the precondition that
makes the rest of the trust spine meaningful: **the PA must be able to prove the
bytes it is adjudicating with are the bytes an operator sanctioned.**

The live posture is a **software** integrity mechanism — content hashing plus a
hardware-key-signed manifest — enforced fail-closed at boot, at model load, and
before every adjudication. Hardware-rooted *sealing* and *measured boot* were
consciously declined (§7); this document describes only what is live.

### 2. The live mechanism

Three composable primitives, all in `shared/models/weight_integrity.py` and
`shared/models/manifest_signer.py`, no external network on any path:

**(a) SHA-256 content verification.** `compute_sha256` streams each weight file in
64-KiB chunks and returns its lowercase hex digest
(`weight_integrity.py:71-88`). The Known-Good Manifest is a JSON document mapping
each weight filename to its expected digest:

```json
{ "version": "1.0.0",
  "digests": { "openvino_model.bin": "<64 hex chars>", … } }
```

`verify_weight_integrity` loads the manifest, looks up the file, recomputes the
digest, and compares (`weight_integrity.py:182-276`). **Every error path returns
`verified=False` — fail-closed by construction.** The full-directory sweep
`verify_all_manifest_entries` additionally rejects any `.bin` present on disk but
**absent** from the manifest — the "swap-and-drop" defense: an attacker who
replaces the primary weight and drops a new filename is caught by the extra-file
check even though no listed digest changed (`weight_integrity.py:400-428`). The
nested sibling `verify_all_manifest_entries_nested` extends coverage to the
OpenVINO `.xml` compute-graph topology and `model_index.json` for the
diffusers-layout image models, and rejects manifest keys that escape the model
directory via path traversal (`weight_integrity.py:438-630`).

**(b) TPM-signed manifest.** The manifest itself is signed so that an attacker who
can write the manifest file cannot forge a matching digest list. The signature
is an **ECDSA P-256** signature produced by a **non-exportable** key generated
*inside* the platform TPM 2.0 via the Windows CNG *Microsoft Platform Crypto
Provider* (`tpm_signer.py:38-39, 150-178`); the private key cannot be exported
even by the process that created it (the CNG default for persisted keys;
asserted by `test_tpm_signer`). `sign_manifest` writes a detached
`<manifest>.sig` (raw signature bytes, base64url-encoded) and a `<manifest>.pub`
(the public key as a Subject-Public-Key-Info PEM, for off-box cross-check)
alongside the manifest (`manifest_signer.py:67-114`). The canonical key name is
`BlarAI-Manifest-Signing` (`manifest_signer.py:44`).

Verification checks the signature **before** the manifest content is trusted:
`load_manifest_verified` calls `verify_manifest_signature` first, then parses
(`weight_integrity.py:130-179`; `manifest_signer.py:122-239`). This ordering
closes the swap-both-files gap — an attacker with local write access would also
need the non-exportable TPM key.

> **Naming note (accuracy).** The manifest is **TPM-signed**, not
> "Pluton-sealed." On the reference unit the active TPM 2.0 is an
> STMicroelectronics part; Microsoft Pluton is present but is *not* serving as
> the TPM (`tpm_signer.py:10-13`). Older docstrings in
> `weight_integrity.py:4-12` still say "Pluton-sealed" and describe a
> hypervisor-enforced copy-on-write layer — that language is stale and is
> **superseded by §7**.

**(c) Fail-closed enforcement (`require_signed_manifest`).** The flag gates the
signature requirement:

- **`false`** — a *missing* `.sig` is permitted with a loud WARNING (the unsigned
  state is never silent); a *present-but-invalid* `.sig` is still fail-closed, so
  no silent downgrade is possible (`manifest_signer.py:164-178, 224-232`).
- **`true`** — a missing **or** invalid `.sig` returns `None` and blocks the load
  entirely (`manifest_signer.py:171-178`).

The shipped configuration sets **`require_signed_manifest = true`** in the Policy
Agent (`services/policy_agent/config/default.toml:26`), the Assistant
Orchestrator (`services/assistant_orchestrator/config/default.toml:578`), and the
image-generation path (`services/assistant_orchestrator/config/default.toml:302`).
The Python default in code is `False` (`entrypoint.py:106, 648-649`) — the
capability ships built-but-off and the shipped config flips it on, which is why
the production-posture benchmark runs record `require_signed_manifest=true`
(`PERFORMANCE_LOG.md:465, 1047`).

### 3. When verification runs — three cadences

| Cadence | Where | What it hashes | On failure |
|---|---|---|---|
| **Boot gate** | PA measured-boot `weight_integrity_gate` step (`entrypoint.py:453-458` → `_phase_weight_integrity` `340-354` → `_verify_weight_integrity_gate` `924-938`); the preceding config step also loads the manifest signature-checked in `_validate_security_material` (`entrypoint.py:833-862`) | Confirms the manifest loads (signature-verified when `require_signed_manifest=true`) and the primary model digest is present + well-formed | Boot step returns `False`; after `MEASURED_BOOT_MAX_ATTEMPTS` (3) retries the boot state is `hard_locked` and the PA does not start (`boot.py:117-159`) |
| **Model load** | `load_model()` in both services calls the full sweep `verify_all_manifest_entries` (`gpu_inference.py:773`, AO `gpu_inference.py:743`); the shared pipeline verifies target + draft (`shared_pipeline.py:322-335`) | Every `.bin` in the manifest + rejects any extra `.bin` | Load returns `False`; the model is not brought up |
| **Per-adjudication (event-triggered)** | Adjudicator Stage 2, gated by `has_integrity_checking` (`adjudicator.py:370-382`) | Re-hashes the **primary model binary only** (`self._model_bin_path`) with `require_signed` matching the boot gate | Synthesizes a `DENY` classification and fail-closes the decision (`adjudicator.py:386-419`) |

The per-adjudication re-verify runs on **every** adjudication and records its cost
as `integrity_ms` on the decision's latency record (`adjudicator.py:383-384,
413-417`). It deliberately re-hashes only the one primary weight binary, not the
full sweep — the full multi-file sweep is a boot/load-time cost, the
per-request check is the cheap in-place-tamper tripwire. (No dedicated
per-adjudication `integrity_ms` figure is published in `PERFORMANCE_LOG.md` at
the time of writing — see Open Questions.)

The boot step is named `attestation_gate` in code for schema-compatibility
(`entrypoint.py:447-452`); what it executes live is configuration load plus
software security-material validation, **not** a TPM Platform-Configuration-
Register measured-boot attestation. The `boot.py` docstring's "Verify TPM/Pluton
attestation" line (`boot.py:9`) is stale relative to §7.

### 4. Actual signing coverage

Weight `.bin` files are gitignored; the digest comparison happens at runtime
against the operator's real weights. The table below is **accurate to the
on-disk `manifest.json` / `manifest.json.sig` presence** in the operator
checkout plus the config declarations — it is *not* a claim that all weights are
signed.

| Model (role) | Manifest? | Signed (`.sig`)? | Source of truth |
|---|---|---|---|
| **qwen3-14b/openvino-int4-gpu** — resident brain (PA + AO), ADR-012 | Yes | **Yes** | `manifest.json` + `.sig` + `.pub` on disk; PA `model_dir` + `weight_manifest` (`default.toml:14-15`) |
| **sdxl-uncensored/openvino-int8-gpu** — UC-010 photoreal | Yes | **Yes** | `manifest.json` + `.sig` + `.pub` on disk; AO `[image_generation].weight_manifest` (`default.toml:251`) |
| **sdxl-illustration/openvino-int8-gpu** — UC-010 illustrate/cartoon base | Yes | **Yes** | `manifest.json` + `.sig` + `.pub` on disk |
| **qwen3-0.6b/openvino-int4-gpu** — configured speculative-decoding draft | Yes | **No** | `manifest.json` only; PA `draft_model_dir` (`default.toml:16`) |
| **qwen3-0.6b-pruned-6l/openvino-int8-gpu** — pruned draft variant | Yes | **No** | `manifest.json` only |
| **qwen2.5-1.5b-instruct/openvino-int4-npu** — fallback | Yes | **No** | `manifest.json` only |
| **bge-small-en-v1.5** — embeddings (NPU) | **No** | No | no manifest on disk |
| **whisper-small** — speech-to-text (GPU) | **No** | No | no manifest on disk |
| **kokoro** — text-to-speech | **No** | No | no manifest on disk |
| **qwen3-vl-8b-instruct** — vision-language model | **No** | No | no manifest on disk |

Evaluation / candidate models present on disk (`qwen3-1.7b`, `qwen3-8b`,
`qwen3.6-27b-int4-ov`) are not runtime models and carry no manifest.

**Coverage summary:** the two weight classes whose bytes directly drive a
Policy-Agent verdict or a UC-010 generation — the resident 14B and the two
Stable Diffusion XL image models — are **TPM-signed**. The speculative-decode
draft and the fallback model are **manifested but unsigned** (their digests are
checked at boot/load, but the digest list itself is not signature-protected
unless/until re-signed). The embedding, speech, and vision-language support
models carry **no manifest at all** — they are outside integrity coverage today.
See §6 for the residual-gap disposition.

### 5. Divergence / failure behavior + logging

- **Boot mismatch or missing/invalid signature** → the `weight_integrity_gate`
  step returns `False` with error code `PA_BOOT_WEIGHT_VERIFY_FAILED`; after 3
  attempts the boot `hard_locked` flag is set and the PA refuses to start. All
  downstream services receive DENY until the PA reaches `ready` — the PA never
  runs in a degraded state (`boot.py:16-18, 156-159`;
  `entrypoint.py:347-354`).
- **Runtime (per-adjudication) mismatch** → the adjudicator logs
  `"Adjudication … runtime integrity FAILURE"` and returns a fail-closed `DENY`
  for that request, persisting the context with the failed
  `IntegrityCheckResult` (`adjudicator.py:386-419`).
- **Extra unlisted `.bin`** → fail-closed rejection at load
  (`weight_integrity.py:400-428`).
- **Logging location.** Verification code logs through the standard library
  logger `shared.models.weight_integrity` / `shared.models.manifest_signer`;
  every fail-closed branch emits `logger.error(...)` naming the file and reason
  (e.g. `manifest_signer.py:173-178, 224-232`). Boot failures are additionally
  captured as structured `error_code` / `error_message` on the `BootState`
  (`boot.py:133-159`). A denied adjudication is written to the tamper-evident
  audit chain via the adjudicator's `_persist_context_with_car` path, so an
  integrity-driven denial is forensically recorded, not only logged.

### 6. Provisioning / re-signing the Known-Good Manifest

The manifest and its signature are produced by an **operator-run, LA-present**
ceremony — `docs/runbooks/manifest_signing_ceremony.md` (FUT-04 / ADR-018). The
sequence:

1. **Preflight (read-only):** `python -m shared.security.ceremony_preflight`
   reports which security material is present (signing key, staged manifest) and
   changes nothing.
2. **Stage:** `python -m shared.models.stage_production_manifest` computes the
   SHA-256 digests of the actual on-disk weights and writes `manifest.json`
   (`--nested` for the diffusers-layout image models).
3. **Sign:** `python -m shared.security.provision_manifest_signing_key` creates
   the non-exportable TPM key `BlarAI-Manifest-Signing` (idempotent), signs the
   manifest, and writes `manifest.json.sig` + `manifest.json.pub`. It prints the
   **SHA-256 of the Subject-Public-Key-Info DER** — the recorded public **trust
   anchor** identifying which chip signed the manifest.
4. **Confirm:** re-run the preflight; the signing-key line should read `OK`.
5. **Flip:** the developer/agent sets `require_signed_manifest = true` and merges
   (a reversible one-line config change — the operator touches no code).
6. **Verify first signed boot:** `python -m launcher`; the startup log emits
   `"Manifest signature verified: manifest=… key=BlarAI-Manifest-Signing"`, the
   operator-visible proof.

**Re-sign after a legitimate weight update:** re-run stage → sign; the same TPM
key is reused, no new ceremony. `sign_manifest` is model-agnostic (flat and
nested layouts).

**Audit surface & gaps.**
- The SPKI-DER fingerprint is the durable, human-recordable trust anchor; the
  signing key is TPM-resident and non-exportable, so the audit question "who
  signed this manifest" reduces to "which chip holds `BlarAI-Manifest-Signing`."
- **No standalone on-demand "verify these weights now" command-line tool
  exists.** The sanctioned read-only surface is `ceremony_preflight` (presence /
  readiness) and the authoritative signature-plus-digest verification happens at
  boot (the launcher log line) and per adjudication; `stage_production_manifest`
  recomputes digests but as a *staging* step, not a verify-and-report check. A
  dedicated operator verify CLI is a coverage gap (see Open Questions).
- **Signing-coverage gaps (§4):** the speculative-decode draft and the fallback
  model are manifested-but-unsigned; the embedding / speech / vision-language
  support models are unmanifested. These are the residual gaps for the LA to
  triage — closing them means staging + signing those manifests in a future
  ceremony. They are not defects in the mechanism; they are the current bounds of
  its **application**.

### 7. Out of scope — declined 2026-07-15

On 2026-07-15 the Lead Architect **declined full hardware-rooted trust**. The
boundary is explicit: **signed-manifest + SHA-256 content verification + TPM
signing STAY live** (§1–§6); the hardware-*sealing* and measured-boot layers are
declined and MUST NOT be documented or implemented as live controls. The
following are consciously out of scope:

- **Pluton / TPM hardware-*sealing* of the manifest (Platform-Configuration-
  Register-bound keys).** Declined. The signing key stays TPM-resident,
  non-exportable, and access-control-locked — but it is **not** PCR-bound.
  On-disk anchor: **ADR-028 Amendment 1 (2026-06-10)** records the key-sealing
  variant as decided-against, informed by the 2026-06-09 on-chip PCR-seal
  proof-of-concept that proved it *feasible* and was nonetheless not adopted.
- **Measured boot (TPM PCR attestation of the firmware / bootloader / OS
  boot-chain).** Declined. This was ADR-028's deferred post-gate item (#627);
  the 2026-07-15 decision closes it rather than pursuing it. The live
  `attestation_gate` boot step performs **software** security-material
  validation only (§3), despite its legacy name.
- **Hypervisor-enforced copy-on-write prevention / read-only page protection with
  write-fault termination** (the "Layer 3" described aspirationally in
  `weight_integrity.py:10-12`). **Not implemented.** No such enforcement is
  wired; the module docstring's three-layer framing predates this decision and
  is superseded here.

**Rationale for the boundary.** Sealing and measured boot defend a
*threat-orthogonal* surface (the firmware/boot-chain and physical-possession
attacker) at the cost of brittle, hardware-generation-coupled ceremonies. The
declined items would bind the system's ability to boot to specific PCR values and
a specific chip, undermining the decades-scale, survives-hardware-generations
design goal, for a threat the software mechanism (a signed digest list verified
fail-closed on a non-exportable key) already substantially covers against the
in-scope attacker (local write access without the TPM private key). The live
mechanism is the deliberate stopping point, not a way-station toward sealing.

## Open Questions

1. **No standalone weight-verify CLI.** The ticket (#23) asked for a manual
   operator verification command; none exists today beyond `ceremony_preflight`
   (presence-only) and the boot/adjudication paths. Whether to add an on-demand
   `verify` command is an LA capability call.
2. **Per-adjudication `integrity_ms` is unpublished.** The adjudicator records it
   per request but no community-grade figure is in `PERFORMANCE_LOG.md`; a
   measured cadence/latency line would complete this record.
3. **Unsigned/unmanifested support models (§4/§6).** Extending coverage to the
   draft, fallback, embedding, speech, and vision-language models is a scope
   decision for the LA, not a mechanism change.

## Verified against

- `shared/models/weight_integrity.py:4-12` (stale docstring), `:71-88`
  (`compute_sha256`), `:91-179` (manifest load + signature-first
  `load_manifest_verified`), `:182-276` (`verify_weight_integrity`), `:297-435`
  (`verify_all_manifest_entries` + extra-file rejection), `:438-630`
  (nested sweep + traversal guard).
- `shared/models/manifest_signer.py:44` (key name), `:67-114` (`sign_manifest` →
  `.sig` + `.pub`), `:122-239` (`verify_manifest_signature`, fail-closed
  contract, require_signed semantics).
- `shared/security/tpm_signer.py:10-13` (STMicroelectronics TPM, Pluton not the
  TPM), `:38-39` (ECDSA P-256), `:150-178` (non-exportable persisted key),
  `:189-237` (sign / verify).
- `services/policy_agent/src/boot.py:1-23` (boot order docstring), `:117-159`
  (retry → `hard_locked`).
- `services/policy_agent/src/entrypoint.py:106, 648-649` (code default `False`),
  `:310-354` (attestation + weight phases), `:446-485` (measured-boot steps),
  `:833-862` (`_validate_security_material`), `:924-938`
  (`_verify_weight_integrity_gate`).
- `services/policy_agent/src/adjudicator.py:370-419` (Stage-2 re-verify,
  fail-closed DENY).
- `services/policy_agent/src/gpu_inference.py:773`,
  `services/assistant_orchestrator/src/gpu_inference.py:743`,
  `shared/inference/shared_pipeline.py:322-335` (load-time sweeps).
- `services/policy_agent/config/default.toml:14-16, 26`,
  `services/assistant_orchestrator/config/default.toml:251, 302, 578`
  (`require_signed_manifest = true`).
- On-disk coverage: `models/qwen3-14b/openvino-int4-gpu/{manifest.json,.sig,.pub}`,
  `models/sdxl-uncensored/…/{manifest.json,.sig,.pub}`,
  `models/sdxl-illustration/…/{manifest.json,.sig,.pub}` (signed);
  `models/qwen3-0.6b/openvino-int4-gpu/manifest.json`,
  `models/qwen3-0.6b-pruned-6l/openvino-int8-gpu/manifest.json`,
  `models/qwen2.5-1.5b-instruct/openvino-int4-npu/manifest.json` (manifest, no
  `.sig`); `bge-small-en-v1.5`, `whisper-small`, `kokoro`,
  `qwen3-vl-8b-instruct` (no manifest).
- `docs/runbooks/manifest_signing_ceremony.md` (provisioning ceremony).
- `docs/DECISION_REGISTER.md` — ADR-028 + Amendment 1 (keys not PCR-bound).
- LA decision 2026-07-15 — full hardware-rooted trust declined (sealing +
  measured-boot); signed-manifest + SHA-256 + TPM signing stay live.

*Live software posture. Hardware-rooted trust (sealing, measured boot,
copy-on-write termination) declined 2026-07-15 — see §7.*
