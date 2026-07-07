# ADR-033 — UC-010: Local Generative Imaging (text→image + image+text→image)

**Status:** PROPOSED 2026-06-16 (LA-approved-with-amendments 2026-06-15 — the implementation
plan `you-are-a-solutions-fuzzy-seal.md` is the approved spec; this ADR records the decision).
Built **DORMANT** — `[image_generation].enabled=false` ships and the uncensored SDXL model is
gitignored, so the capability ships absent. Going live is a SEPARATE LA-present ceremony.
**Deciders:** Lead Architect (blarai); code-specialist (build).
**Builds on:** ADR-011 (all model inference on the Arc 140V GPU), ADR-025 (at-rest encryption —
the DEK/field-cipher/AAD posture the new `generated_images` table joins), ADR-023 (provenance-based
trust + the GUARDED tool tier + #570 AO→PA tool-dispatch mediation), ADR-032 (UC-003 display-only
images — the `blarai-img://` scheme + the no-VLM structural lock + the BED-1 purpose-deny pattern this
mirrors), ADR-015 / BUILD_JOURNAL §19 (which named image generation an "honest future track").
**Relates to:** Vikunja #666; `Use Cases_FINAL.md` §010 (UC-010 — newly authored, deliberately
expanding the canonical 9-Use-Case vision, LA-directed).

## Context

The Lead Architect wants BlarAI to generate images locally: (1) **text → image**, and (2) **image +
text → image** (image-conditioned editing / img2img). None of the canonical 9 Use Cases covers this —
the build journal (§19) and ADR-015 named image generation an *"honest future track"* requiring a
separate diffusion model. UC-010 builds that track with an **uncensored** generator, fully local on
the Arc 140V iGPU via OpenVINO GenAI, with **zero external network**, **fail-closed**, and
**born-encrypted** at rest.

The capability is **memory-hostile**: the diffusion model (\~4.4 GB INT8) cannot co-reside with the
always-resident 14B (\~8.7 GB) + KV-cache + draft + embedder + voice on the 31.323 GB shared ceiling
without eviction discipline. A Phase-0 memory spike was run as a build-or-no-build gate *before* this
build (see §Memory posture).

Three facts shaped the design, verified against the installed stack before building: (1)
`openvino-genai 2026.1.0.0` ships `Text2ImagePipeline` / `Image2ImagePipeline` (+ `InpaintingPipeline`),
and an SDXL finetune converts via `optimum-cli export openvino` with the diffusers `safety_checker`
**not** emitted into the OpenVINO pipeline — so "uncensored" is purely the checkpoint, not a removed
guardrail; (2) the existing `vlm.py` load-on-demand + Fail-Soft + `unload()` module is the exact
template for a GPU-pipeline lifecycle that yields the GPU back; (3) the knowledge bank's `_embed`
call sites already carry a fail-closed `str`-only guard, so a structural no-VLM guarantee for
generated pixels is enforceable, not merely promised.

## Decision

1. **Local-only, uncensored, on the Arc 140V via OpenVINO GenAI.** The model is an uncensored
   SDXL-Lightning finetune (provisioned: **RealVisXL V5.0**, INT8 nncf weight-only, diffusers-OV
   layout). The runtime NEVER fetches weights; conversion + download is a provisioning-time act.
   Model-agnostic (`[image_generation].model_dir`) — a later checkpoint swap is config, not a rewrite.

2. **Two modes (v1): text→image + image+text→image (img2img).** `Text2ImagePipeline` and
   `Image2ImagePipeline`. The img2img **seed image is a LOCAL file or a stored `blarai-img://<id>`
   reference — NEVER a URL.** No mask UI required. Masked inpaint (`InpaintingPipeline`) is a named
   fast-follow (needs a WinUI mask tool); true instruction-editing (FLUX Kontext / Qwen-Image-Edit) is
   a documented future track (no OpenVINO path today + memory-hostile).

3. **Content safety = governance + a go-live attestation, NOT a classifier (LA decision).** Uncensored
   for all *legal* content; **NO classifier, NO prompt tripwire, NO prompt inspection.** See
   §Content safety for the full posture: the immovable legal boundary is named explicitly, recorded as
   the operator's sole documented responsibility and a deliberate ACCEPTED-RISK, with an honest
   statement that robust *local technical* control at that boundary is not achievable, gated by a
   one-time operator attestation at go-live.

4. **Born-encrypted, display-only output; DELETE-on-discard.** Generated images are stored in a new
   `generated_images` table under the SAME shared DEK (ADR-025 §2.1 one-DEK rule), each content-bearing
   column (`prompt`, `data`) AAD-bound to `generated_images|<column>|<session_id>|<image_id>`. The bytes
   are **born on-box from an operator prompt, are display-only, and are NEVER chunked, embedded,
   indexed, or fed to any model** (the no-VLM lock — the same fail-closed `str`-only `_embed` guard
   ADR-032 relies on). Retention is DELETE-on-discard (ADR-032 parity): a discarded generation is reaped
   outright, no tombstone. The reap is a true at-rest zeroing — the `generated_images` store opens with
   `PRAGMA secure_delete=ON` (UC-010 WS2), so the deleted ciphertext is overwritten in the freed pages
   rather than merely unlinked (the SE-1 residual probe enforces it).

5. **GUARDED tool tier; NO Policy-Agent adjudication-logic change.** `generate_image` is registered in
   `tools._REGISTRY` + `pgov.TOOL_CALL_ALLOWLIST` at `RiskTier.GUARDED` (local action, redirectable
   prompt parameter, no egress ⇒ Layer-3-lockable under untrusted content, `/trust` the sole override —
   NOT `DANGEROUS`, which is for egress/irreversible external dispatch; NOT `SAFE`, which a heavy local
   action is not). A local `tool:generate_image` CAR matches no restricted-path / URL / exfil rule and
   the PA's existing `DeterministicPolicyChecker` returns ALLOW — **no rule is added or changed**. See
   §Go-live for the BED-1-style purpose-deny reconciliation.

6. **Generation runs IN THE AO PROCESS.** The AO owns the GPU pipeline lifecycle, the at-rest
   FieldCipher, and the knowledge bank, so no second process contends for the GPU and eviction lives in
   one place. The gateway intercepts `/imagine` / `/edit` / `/save`, forwards an `IMAGE_GEN_REQUEST` over
   the existing mTLS IPC, the AO generates + stores born-encrypted, and returns a `blarai-img://<id>`
   reference. WinUI renders it inline (zero C# change). **Because generation holds the diffusion pipeline
   lock, the assistant is blocked for the generate window** (a few seconds for few-step SDXL) — a named
   UX cost (§UX cost).

7. **Ships DORMANT behind a master weld lock.** `[image_generation].enabled=false` is the shipped
   default, AND the model is gitignored (absent), so `image_gen.is_available()` is False and nothing
   ever loads. `/imagine` + the `generate_image` tool degrade to a clear "generation unavailable" notice
   with NO load attempted. Going live is a SEPARATE LA-present ceremony with its own verification — NOT
   folded into another go-live (§Go-live).

## Memory posture (load-on-demand + eviction; fail-soft)

The diffusion model loads on demand and is evicted after EVERY generate (`image_gen.unload()` in the
caller's `finally` — the SOLE live eviction; it runs on every generate including the failure path, and
the only way it is skipped is whole-process exit, which reclaims GPU memory anyway). `idle_unload_s` is a
RESERVED config knob (validated + plumbed, NOT yet consumed by a daemon — the per-generate `finally`
makes one unnecessary here; a timer mirroring substrate #611 is a documented future option, not a shipped
backstop). GPU compile props
deliberately OMIT `MODEL_PRIORITY="HIGH"` — the diffusion model yields to the always-resident 14B, never
the reverse. Before loading, the AO evicts the OTHER large resident caches: `unload_vlm()` (\~5 GB) +
the substrate embed cache + the knowledge-bank caches. **The 14B is NEVER evicted.** (The AO process
holds no voice engine — STT/TTS live on the gateway/backend side — so there is no AO-side voice unload;
named honestly, not silently skipped.)

**Amendment 2 (2026-06-17, #666 go-live — hires-fix eviction):** the "14B is NEVER evicted" invariant
above is RELAXED for the hires-fix path ONLY. A hires-fix refine (1536² img2img — see §quality, the fix
for soft faces in wide shots) measured **\~26 GB standalone** and does NOT co-reside with the resident 14B
in 31.323 GB — it thrashed the 14B out to disk (`proc_rss` collapsed to 142 MB; \~2 min). So for a HIRES
generate the AO evicts the shared 14B for the duration via `SharedInferencePipeline.unload()`, and the
14B is **lazily reloaded** on the next PA/AO `generate()` (\~15-30 s, paid once). The 14B is shared by the
Policy Agent AND the AO through one `SharedInferencePipeline` wrapper; both route `.generate()` through it
and neither caches pipeline-instance state (the AO tokenizer is disk-loaded; the PA passes string
prompts), so the reload is transparent to both. **BASE (non-hires) 1024² generates still fit co-resident
and KEEP the 14B** (no reload cost) — the eviction is gated to `[image_generation].hires_enabled`. The
imagine-path IPC fail-safe is raised 90→175 s (under the 180 s socket cap) for the longer two-pass.
Measured even with the 14B evicted, a 1536² hires peaks at \~294 MB free — it fits, but `hires_factor` can
be lowered (1.25) for margin. Fail-Soft: any hires-refine failure (incl. OOM) returns the base image.

**Phase-0 spike (build-or-no-build GATE — PASSED, real Arc 140V, 2026-06-16):** with the 14B resident +
\~3k-token KV-cache, an SDXL INT8 co-resident load + a 1024² generate peaked at **\~26.0 GB** vs the
**31.323 GB** ceiling (**5.3 GB headroom**); SDXL load 18.7 s; 1024² generate 10.7 s; no swap-thrash, no
OOM. The budget closes WITH the 14B held resident — so the "14B never evicted" invariant holds and the
build proceeded. (NOT measured: VLM + voice co-residency during a generate — the eviction sequence
removes them first; dataset-calibrated INT8 quality; image fidelity.) Fail-Soft means an unexpected OOM
degrades to the "generation unavailable" notice, not a host freeze.

## Content safety (decision 3 — the full posture)

- **The immovable legal boundary, named explicitly.** It is illegal to generate or possess child
  sexual abuse material (CSAM) and content that is obscene under the operator's jurisdiction. That
  boundary is absolute and is not a matter of configuration. Generating such content is forbidden;
  nothing in this capability is intended to facilitate it.
- **The operator's sole documented responsibility + a deliberate ACCEPTED-RISK.** BlarAI is a
  single-operator, local, no-egress system. The uncensored generator will produce whatever *legal*
  content the operator prompts for; staying within the legal boundary above is **the operator's sole
  documented responsibility**, recorded here as a deliberate **ACCEPTED-RISK**. The reasoning: the
  alternative (a censoring classifier) trades a real, broad loss of legitimate capability for a control
  that does not actually hold the boundary (next bullet), on a private single-user box where the
  operator is the only party and there is no distribution surface.
- **Robust local technical control at that boundary is NOT achievable — honestly stated.** There is no
  local hash database (the lawful CSAM-detection corpora — e.g. NCMEC/PhotoDNA — are not distributable
  to a private box, and matching is for *detecting shared* material, not gating *generation*); prompt
  denylists are trivially bypassable (synonyms, obfuscation, img2img) and produce false refusals on
  legitimate prompts. A classifier here would be **security theater** — it would not hold the boundary
  and would degrade the capability. So the chosen control is **governance + a go-live acknowledgment,
  not a classifier.**
- **One-time operator attestation at go-live.** Before `[image_generation].enabled` is flipped to true,
  the go-live ceremony records a one-time operator attestation (in the ledger + journal) that the
  operator understands the legal boundary above and accepts sole responsibility for staying within it.
  This is the control: a deliberate, recorded, human acknowledgment — not an automated gate.
- **Structural mitigations that DO hold.** The output is operator-initiated, audited (the AO records
  generation in its chain), no-egress (the image never leaves the box — no distribution), and
  display-only/born-encrypted/DELETE-on-discard. These bound the *consequences* structurally even though
  the generation boundary itself is governance-held.
- **Revisit trigger.** This posture is revisited ONLY if a share/export capability is ever added — that
  would create a distribution surface and change the calculus.

## Threat model (threat → control → residual)

- **Prompt-injection driving generation from untrusted content** → `generate_image` is GUARDED
  (Layer-3 action-lock fires under UNTRUSTED content, `/trust` the sole override) + the #570 per-dispatch
  PA deny runs for every tool + the dormancy gate. No egress ⇒ no exfil-by-rendering. **Residual:** a
  deletable on-box artifact — low harm, ACCEPTED.
- **`/edit` input image** → **no URL ever** (a URL seed is refused loudly BEFORE any handling); the seed
  is a LOCAL file (UNC/network refused raw+resolved, extension allowlist, containment, size cap) or a
  stored `blarai-img://` ref; the bytes cross to the AO via the encrypted `image_staging` blob, never a
  frame, never plaintext. **Residual:** a host-side image-decoder CVE bounded by Fail-Soft + no egress,
  ACCEPTED.
- **GPU-OOM / memory DoS** → hard caps (`max_width`/`max_height`, `steps`) as circuit breakers
  (over-cap CLAMPS, never honored blindly; the config validator bounds the caps so a misconfig cannot
  disable the breaker); load-on-demand + evict + Fail-Soft. **Residual:** within-cap VRAM; cap values
  validated against the Phase-0 baseline, ACCEPTED.
- **Content safety** → governance + the go-live attestation, not a classifier (see §Content safety).
  **Residual:** the generation boundary is governance-held; consequences are bounded structurally
  (operator-initiated + audited + no-egress + no-distribution). ACCEPTED.
- **At-rest leakage** → born-encrypted `generated_images` (ADR-025 DEK, fresh nonce/field, AAD-bound to
  `session_id|image_id`), DELETE-on-discard, the prompt encrypted alongside the bytes. **Residual:**
  plaintext pixels in RAM during a run (ADR-025 §3 deferred-not-denied), ACCEPTED.
- **Model-weights supply chain** → provisioning-time SHA-256 manifest over the nested layout,
  verified at load fail-closed (`verify_all_manifest_entries_nested` — a sibling of the flat sweep,
  added because the diffusers-OV layout puts weights in subdirs the flat globber misses). Coverage is
  every nested `.bin` weight AND every OpenVINO `.xml` topology file AND `model_index.json` (UC-010 WS1
  — so a write-capable local actor cannot swap the compute graph or the pipeline index past a `.bin`-only
  digest list): the load refuses on any missing/tampered/extra `.bin`/`.xml`/`model_index.json`. With
  `[image_generation].require_signed_manifest=true` (the shipped setting) the manifest must ALSO carry a
  valid TPM `.sig` (verified via `load_manifest_verified`, FUT-04 parity with the signed 14B/PA boot) or
  the load refuses fail-closed; a None/absent manifest path under `require_signed_manifest=true` also fails
  closed (you cannot sign-verify a manifest that does not exist). Only with `require_signed_manifest=false`
  does a None manifest SKIP the check with a loud WARNING (the dormant-dev posture, never silent). The
  go-live ceremony (`docs/runbooks/uc010_image_gen_go_live.md`) stages the nested manifest
  (`stage_production_manifest --nested`) then SIGNS it (`manifest_signer.sign_manifest`) before
  `enabled=true`; the runtime never fetches weights. **Residual (1) — CLOSED on the nested (image) path:**
  the `.xml` topology + `model_index.json` are now hashed + required + signature-verified on the NESTED
  path. Scoped NESTED-ONLY by design: the FLAT verifier (`verify_all_manifest_entries`), the flat stager,
  and the already-signed 14B/PA/draft manifests are UNCHANGED — extending the flat verifier to demand
  `.xml`/`model_index.json` would refuse the next real 14B boot (its signed manifest is `.bin`-only;
  re-covering it is a separate re-stage + re-sign ceremony). A flat `.bin`-only regression lock proves the
  14B shape still verifies. **Residual (2):** trust in the chosen checkpoint at provisioning, ACCEPTED.
  **Residual (3) — ACCEPTED:** the nested sweep covers `.bin` + `.xml` + `model_index.json`, but NOT the
  per-component non-weight metadata — the per-component `config.json`, `scheduler/scheduler_config.json`,
  and tokenizer files (`tokenizer.json` / `vocab.json` / `merges.txt` / `tokenizer_config.json` /
  `special_tokens_map.json`). These are deliberately out of manifest scope for now: a low-severity
  local-supply-chain edge (a write-capable local actor could alter a scheduler/tokenizer config past the
  digest list, though they cannot swap the compute graph or weights, which ARE covered). A future re-stage
  can widen the manifest to include them (mechanical — add the keys + re-sign); recorded here so the gap is
  on the record like Residual (2), not silent.

## Output provenance

A generated image is **born on-box from an operator prompt** — it is the operator's own creation, not
ingested untrusted content. It is **display-only**: never chunked, embedded, indexed, retrieved, or fed
to any model. The `blarai-img://<id>` ref is local + non-navigable; the only ImageSource the renderer
builds is a locally-decrypted pixel buffer (never a URL/network source). This is distinct from UC-003
display-only *article* images (which are untrusted external content) — but both share the no-VLM lock
and the born-encrypted store.

## Invocation + the purpose-deny weld-lock reconciliation

`/imagine <prompt>` (text2image) and `/edit <local|blarai-img://> <prompt>` (img2img) are explicit
gateway commands (generation is never inferred from conversational text); `/save <id> <path>` is the
TUI display fallback. The gateway intercepts them, builds `IMAGE_GEN_REQUEST`, and the AO's handler
runs the §Memory-posture orchestration. The `generate_image` AO tool (in `_REGISTRY`) is a
never-raising in-loop shim that directs the model to `/imagine` (the heavy generate runs in the
IMAGE_GEN_REQUEST handler, which has the session id + cipher the in-loop form lacks).

**Reconciliation with go-live's "lift the image-gen purpose-deny" (BED-1 pattern).** Unlike UC-003's
binary-image fetch — which rides the shared egress door and needs a `url_adjudicator` purpose-deny —
UC-010 `generate_image` is a LOCAL tool with no egress, so there is no egress door to weld. Its
equivalent weld lock is the `[image_generation].enabled` master flag combined with the model's
structural absence: `is_available()` False ⇒ the handler returns "unavailable" with no load. Going live
is the config flip + the operator attestation — a **config/registration step, NOT an
adjudication-logic change** (decision 5). The PA deny rules are byte-identical before and after go-live.

## Display

WinUI: **zero C# changes** — `blarai-img://<id>` (the UC-010 ids use the SAME `uuid4().hex` 32-hex
shape the existing `ImageResolver.cs` already validates with `\A[0-9a-f]{32}\z`); `MarkdownBlock.cs`
renders it. Host-side: a Python resolver (`generated_image_resolver`) reads `generated_images` first
(then `knowledge_images` as a fallback), decrypts → bitmap bytes, with the id gate anchored full-string.
TUI: `/save <id> <path>` writes the decrypted PNG on explicit request (the TUI has no inline image
surface).

**Resolve grain — GLOBAL-BY-ID (deliberate accepted posture, LA 2026-06-16, recorded on #666).** A
`generated_images` row resolves by `image_id` alone (`get_generated_image(image_id)` — no session
predicate), so a `blarai-img://<id>` resolves from ANY of the operator's sessions. This is deliberate:
generated images are **operator-owned creations** forming one cross-session collection (e.g. `/edit` can
seed from any prior generation), not per-session-compartmented artifacts. Per-session scoping
(`WHERE image_id=? AND session_id=<current>`) was considered and rejected because its security delta is
**nil** in the single-operator / one-DEK / DACL-locked-pipe / display-only model: access already requires
possession of an unguessable `uuid4().hex` id (a 128-bit bearer handle that only ever appears in the
operator's own transcripts), and the AES-GCM AAD bound to `session_id|image_id` provides tamper-evidence
(a relocated/edited ciphertext fails to decrypt → quarantine). Per-session would add only
access-control-by-requesting-context — a boundary (the operator from themselves) that is not a real trust
boundary here — at the cost of the cross-session `/edit`-seed capability. The asymmetry with ingested
`knowledge_images` (which use the stricter per-document grain `get_knowledge_image(doc_uuid, image_id)`)
is **principled**: ingested images belong to a specific document and are meaningless outside it, whereas
generated images belong to the operator. **Revisit trigger:** if BlarAI ever becomes multi-user /
multi-tenant, re-scope the generated-image resolve grain (the per-document primitive is the template).
The full trade-off rationale is in the journal fragment `docs/journal_fragments/2026-06-16_uc010-resolve-grain-posture.md`.

## Dormancy / go-live

**Dormant (shipped):** `[image_generation].enabled=false` AND the model gitignored (absent). A test
proves dormant-by-default (`is_available()` False, generate returns the unavailable notice, no load).

**Go-live (separate LA-present ceremony — NOT folded into another go-live):** (1) the **one-time
operator content attestation** (recorded in ledger/journal — §Content safety); (2) confirm the weight
manifest verifies on the box — run the UC-010 provisioning ceremony (`docs/runbooks/uc010_image_gen_go_live.md`)
so the nested SDXL manifest is staged (`stage_production_manifest --nested`) + SIGNED
(`manifest_signer.sign_manifest`, the `BlarAI-Manifest-Signing` TPM key), then confirm
`verify_all_manifest_entries_nested` passes over the full `.bin` + `.xml` + `model_index.json` set with
`[image_generation].require_signed_manifest=true`; (3) flip `[image_generation].enabled=true`; (4) **verify LIVE on the Arc
GPU before trusting the flip** — text→image + img2img each produce a real image; born-encrypted
confirmed by a raw-column scan (0 plaintext); a cap fires; the co-residency eviction + Fail-Soft are
observed under `log_memory`; WinUI renders `blarai-img://`; `/edit` refuses a URL; generation appears in
the audit chain; community-grade PERFORMANCE_LOG live numbers recorded; (5) a same-day journal entry.

## UX cost (named)

Generation holds the AO's diffusion-pipeline lock, so **the assistant is blocked for the generate
window** (a few seconds for few-step SDXL; \~10.7 s at 1024² per the Phase-0 spike). This is a deliberate
trade-off: running generation in the AO process keeps the GPU + eviction + cipher in one place (decision
6); the cost is that a generate is not concurrent with a chat turn. A separate-process generator was
rejected (it would contend for the GPU and split eviction across two owners — §Rejected alternatives).

## UC-010 expands the canonical vision (LA-directed)

The canonical `Use Cases_FINAL.md` defines 9 Use Cases; image generation was explicitly named a future
track, not one of them. UC-010 **deliberately expands** that vision at the Lead Architect's direction.
Recorded as such here and in `Use Cases_FINAL.md` §010 so the expansion is on the record, not a silent
scope creep.

## Rejected alternatives

- **A cloud image API** — violates the local-only + no-egress mandate absolutely. Rejected.
- **Co-reside a large model with the 14B (no eviction)** — the memory budget does not close (§Memory
  posture); the 14B-never-evicted invariant forbids it. Rejected in favor of load-on-demand + evict.
- **Feed generated/seed images to the VLM** — treats pixels as a trusted modality and couples the
  generator to vision inference. Rejected (the no-VLM lock holds; generated bytes never reach a model).
- **URL input for `/edit`** — a network egress from an image command; forbidden. Rejected (LOCAL +
  `blarai-img://` seeds only).
- **A content-safety classifier / prompt denylist** — does not hold the legal boundary (no local hash
  DB; denylists bypassable) and degrades legitimate capability — security theater (§Content safety).
  Rejected in favor of governance + the go-live attestation.
- **NPU offload** — retired from the P1 Core Loop (ADR-011); all model inference is on the Arc 140V GPU.
  Rejected.
- **A separate image-gen process** — would contend for the GPU with the AO and split eviction across two
  owners. Rejected in favor of in-AO generation (decision 6), accepting the AO-blocked-during-generate
  UX cost.
- **FLUX.2 Klein (evaluated 2026-06-15, DECLINED)** — no OpenVINO conversion path today; the roadmap
  will not gate on Intel adding one. (The FLUX.1 Kontext demo needed a 24 GB dedicated-VRAM Arc Pro
  B60 — memory-hostile for the Arc 140V regardless.) Instruction-editing remains a documented future
  track, revisited when it lands in a released `optimum-intel` AND a full-LLM-eviction memory strategy
  is proven on the Arc 140V.

## Consequences

- BlarAI gains local image generation (text→image + img2img), uncensored for legal content, fully
  offline, born-encrypted, display-only — a first-class UC-010, dormant until an LA-present go-live.
- A new `generated_images` table + `image_gen.py` module + `imagine_coordinator.py` + the
  `IMAGE_GEN_REQUEST`/`RESULT` IPC pair + the `generate_image` GUARDED tool. No new egress surface (the
  egress security invariants — "exactly one runtime module imports a network client" — still hold).
- The capstone security narrative (#612) gains a documented example of the build→dormant→attested-go-live
  doctrine applied to a generative capability.

## Amendment 3 (2026-06-30 — dispatch asset generation, SEAM A / #714)

The headless-coding **dispatch** (UC-010 ASSETS phase, #666/#670/#688) now generates image assets for a
dispatched build by calling **this same `image_gen.py` generator** — AO-side, at `/dispatch` approve time,
while the 14B is resident and BEFORE the 14B→30B model swap ("SEAM A"). This amendment records the
governance posture for those dispatch-generated assets, which differs from the operator's interactive
`/imagine` output in exactly ONE deliberate way — the store:

1. **Dispatch assets are plain build artifacts, NOT gallery content.** They are written as plain PNGs into
   the target project's working tree (`<repo>/assets/`, or `public/assets/` for web) and committed into
   that repo's baseline — they **do NOT enter the born-encrypted `generated_images` store** (decision 4 is
   not invoked for them). Rationale: they are code-build inputs the operator's *project* owns and versions,
   not private gallery creations. This keeps the encrypted store's DELETE-on-discard / no-VLM semantics for
   what it is for (the operator's `/imagine` collection) and avoids polluting it with dev assets. **No
   second crypto path is introduced** — the dispatch simply skips the store; the generator is otherwise
   unchanged.

2. **Everything else is inherited unchanged.** Same GPU pipeline, same per-generate `unload()` in a
   `finally`, same `generate_image` GUARDED tier + the #570 deterministic PA deny run for each generate,
   same content-safety posture (governance + the go-live attestation, NOT a classifier — the dispatch
   prompt is 14B-authored from the operator's own goal). **No new egress** (the exactly-one-network-client
   invariant holds; nothing is fetched — the asset is born on-box). **No PA adjudication-logic change.**

3. **Memory: base-resolution only, the 14B is KEPT.** Dispatch generation FORCES `hires_enabled=false`, so
   it stays in the proven base-1024² co-resident envelope (§Memory Phase-0, \~26 GB) and never evicts the
   about-to-be-swapped 14B. (Amendment 2's hires 14B-eviction is not used on the dispatch path.) The
   image-model + 30B co-residence remains forbidden (32.5 GB breach) — which is WHY SEAM A generates
   *before* the swap (14B-resident), not during it. A driver-side "SEAM B" `PHASE_ASSETS` is documented as
   the reserve path for a future hires dispatch asset only.

4. **Dormant + fail-soft.** The whole dispatch-asset path ships behind `BLARAI_ENABLE_ASSET_GENERATION`
   (default off) and is wholly fail-soft: any failure (flag off, no specs, model unavailable, PA deny,
   generate/write/commit error) is swallowed and the swap proceeds — the coder falls back to an inline SVG.
   Nothing raises into the EXECUTE handler.

Impl: `feat/uc010-dispatch-asset-gen` (BlarAI — `acceptance.py` asset specs, `entrypoint.py` the SEAM-A
seam) + `feat/uc010-dispatch-asset-w4` (agentic-setup — the coder asset-consumption hint). Live-proven
2026-06-30: a real cartoon elephant generated on the Arc 140V + committed into a repo baseline via the real
code path (perf: `PERFORMANCE_LOG.md` / `docs/performance/uc010_dispatch_asset_gen_2026-06-30.json`).
