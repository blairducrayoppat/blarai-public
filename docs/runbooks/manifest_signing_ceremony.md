# Manifest Signing Ceremony Runbook — locking the model weights to this machine

<!-- doc-rot gate (#994): the config flag(s) gating this ceremony. The EXECUTED banner below must agree with their LIVE state in services/assistant_orchestrator/config/default.toml — read there, never from this doc. -->
<!-- Gating-flags: [security].require_signed_manifest, [security].require_signed_draft_manifest -->

> **For the Lead Architect (non-developer-friendly).** Sprint 16, Stream B, FUT-04.
> This ceremony provisions the 4th TPM key (`BlarAI-Manifest-Signing`) and signs
> the weight-integrity manifest so BlarAI can verify — cryptographically — that
> its model files have not been tampered with between boots.
>
> ## STATUS: EXECUTED — 2026-06-07, extended 2026-07-18. Do not re-run.
>
> **The key exists and is protecting the model weights right now.** This runbook
> was written before that was true, and the "stakes are very low / protecting
> nothing" framing it used to open with is no longer accurate — it has been
> removed rather than caveated.
>
> What actually happened:
>
> - **2026-06-07** (commit `90c148cb`, closing #106): the `BlarAI-Manifest-Signing`
>   TPM key was provisioned on-chip and the 14B weight manifest signed;
>   `require_signed_manifest` flipped to `true`. All four TPM keys were confirmed
>   live on-chip 2026-06-09 (`8203325e`).
> - **2026-07-18** (LA-present ceremony, merge `78b17598`, closing #107): both
>   spec-decode **draft** manifests were signed and `require_signed_draft_manifest`
>   flipped to `true` in the Assistant-Orchestrator and Policy-Agent configs.
>
> **Live state today** — read from config, not from this file:
> `require_signed_manifest = true` and `require_signed_draft_manifest = true` in
> both `services/assistant_orchestrator/config/default.toml` and
> `services/policy_agent/config/default.toml`.
>
> **Re-running is not a no-op.** Step 3 signs manifests and Step 5 flips flags
> that are already flipped. A re-signature over changed weights would silently
> re-baseline what "untampered" means. If a signed boot is failing, that is a
> diagnosis task — start at Step 6's failure guidance, not at Step 1.
>
> This file is kept as the historical script and as the reference for the
> undo/reset path at the end.

---

## The golden rules (read once)

1. **One command at a time.** Run a step, then paste me what it printed. I will
   confirm before you go on.
2. **These commands print only PUBLIC info** (key fingerprints, file hashes) —
   safe to paste to me. There is no secret output in this ceremony.
3. **You never edit code.** The flip to `require_signed_manifest = true` is my
   job (a tiny config change I make and merge); you run the ceremony commands.
4. **Stop anytime.** Stopping between steps is always safe. But note this rule was
   written before the ceremony ran, and it no longer implies "so re-running is
   harmless" — see the EXECUTED banner at the top. The key exists and is protecting
   the weights now; re-signing over changed weights would silently re-baseline what
   "untampered" means.
5. **If a step fails:** don't retry blindly — paste me the error. The most likely
   cause is "the manifest has not been staged yet" (we fix that in Step 2).

---

## Step 0 — Open your terminal (one-time setup each session)

1. Click Start, type **PowerShell**, right-click **Windows PowerShell** →
   **Run as administrator**, and click Yes.
2. In that black window, paste this and press Enter:

   ```
   cd C:\Users\mrbla\blarai
   ```

For every command below, use the project's own Python by pasting the **full path**
shown — you do not need to activate anything.

---

## Step 1 — Look before touching (read-only check)

This **changes nothing**. It reports what security pieces are already in place,
including whether the new manifest-signing key is ready.

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m shared.security.ceremony_preflight
```

**What you will see** — a checklist. After the EA-4 ceremony (Sprint 15), most
lines say `[ OK ]`. When this was written the manifest-signing-key line read:

```
  [ FAIL ]  Manifest signing key           — NOT FOUND
```

> **Not what you will see today.** The key was created on 2026-06-07, so this line
> now reports `[ OK ] … present (BlarAI-Manifest-Signing)` — the Step 4 form. A
> `FAIL` here today would mean something is wrong, not that you are on track.

That *was* expected when this was written — the key is created in **Step 3**
(Step 2 only stages the manifest). If the **TPM sealer / signer** lines say
`NOT available`, stop — that means the security chip is unreachable and we sort
that out first.

**Paste me the whole checklist.** I will tell you which steps you need.

---

## Step 2 — Stage the manifest (if not already present)

If Step 1 showed `Production manifest — NOT FOUND`, run this to compute
fingerprints of your actual model files:

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m shared.models.stage_production_manifest
```

**What you will see** (real example):

```
--- Step 2 of 3 — Compute SHA-256 digests ---
  openvino_model.bin
    SHA-256: 63df8d8aaef6...
--- Step 3 of 3 — Write manifest ---
  Manifest written : ...\manifest.json
  Manifest Staged Successfully
```

Safe to paste. **Paste me the output.**

*(If Step 1 showed `Production manifest — present`, skip Step 2 entirely.)*

---

## Step 3 — Create the manifest-signing key and sign the manifests

This creates (or reuses) one key **inside** your security chip and immediately
signs the manifest files you have on disk. The private key never leaves the chip.
**Key creation** is idempotent — it does nothing if the key already exists. **The
signing is not a no-op**, and this line used to call the whole step "safe to
re-run". Now that the ceremony has run (see the banner at the top), re-signing
would re-baseline the manifests against whatever the weights are *now* — which is
exactly the check you are trying to preserve. Do not re-run this step to "make
sure"; read the banner first.

**Coverage (FUT-05 / #107 + #917):** by default this now signs, with the **same**
key, the authoritative Qwen3-14B manifest **plus both** speculative-decoding **draft**
manifests that BlarAI actually verifies:

- the **shared-pipeline draft** (`qwen3-0.6b-pruned-6l`) — used in the normal
  host-mode run (#107); and
- the **Policy-Agent standalone/fallback draft** (`qwen3-0.6b`) — used when the
  Policy Agent builds its own pipeline (the guest-VM smoke path and tests) (#917).

One key is deliberate: a draft is *non-authoritative* (it only proposes tokens the
signed 14B re-checks), so a tampered draft could only slow things down, never change
an answer. A draft that is not on this machine is simply skipped.

We sign **only what is enforced** — every manifest signed here has a real code path
that verifies it. (Nothing else is signed: `qwen2.5-1.5b` is not a served model, so
it stays out.)

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m shared.security.provision_manifest_signing_key
```

*(If you ever re-converted a draft model, first re-stage its digests with
`... -m shared.models.stage_production_manifest --drafts`, then run the sign
command above. Normally you do not need this — the draft digests are committed.)*

**What you will see:**

```
Manifest signing-key provisioning ceremony (FUT-04 / FUT-05 / ADR-018)
  TPM key name       : BlarAI-Manifest-Signing
  TPM key status     : already existed (idempotent no-op)
  date (UTC)         : 2026-...
  [sign] manifest          : ...\qwen3-14b\...\manifest.json
         signature written : ...\manifest.json.sig
         public key written: ...\manifest.json.pub
  [sign] manifest          : ...\qwen3-0.6b-pruned-6l\...\manifest.json
         ...
  [sign] manifest          : ...\qwen3-0.6b\openvino-int4-gpu\manifest.json
         ...
  manifests signed   : 3
  SHA-256 (SPKI DER) : <64 hex characters — your trust anchor>
Done. Record the SHA-256 fingerprint above as the trust anchor.
...
NEXT: after verifying the signatures on-chip, flip `require_signed_manifest = true`
(14B) and `require_signed_draft_manifest = true` in BOTH the AO config (shared-pipeline
draft) and the PA config (standalone/fallback draft).
```

*(You will see 3 `[sign]` lines only if all three model dirs are on this machine.
Any draft that is not downloaded here is skipped — `manifests signed` will be 2 or
1 accordingly. That is expected and fine.)*

The `SHA-256 (SPKI DER)` fingerprint is **public** — safe to paste, and worth
keeping in a note (it identifies which chip signed the manifest, useful if you
ever provision a second machine).

**Paste me the output.**

---

## Step 4 — Confirm everything is green

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m shared.security.ceremony_preflight
```

You are aiming for the manifest-signing key line to now say `[ OK ]`:

```
  [  OK  ]  Manifest signing key           — present (BlarAI-Manifest-Signing)
```

**Paste me the checklist.** When it says READY (or all OK including the manifest
key), tell me — that is my cue for Step 5.

> **Know what this check does and does not prove (#943).** For draft manifests the
> preflight tests whether a `.sig` file **exists**, not whether it is **valid** —
> `shared/security/ceremony_preflight.py:331` is literally `signed = sig.exists()`.
> So a present-but-invalid or truncated signature reports as signed here. An `OK`
> on this line means "a signature file is in place", not "the signature verifies".
>
> This is a weaker check than it reads, not a hole that reaches production: Step 6
> boots the real system, and that boot verifies the signature fail-closed. An
> invalid signature surfaces there — one step later than you would expect from
> this screen, but it does surface, and it stops the boot rather than passing
> silently. Treat Step 6, not this checklist, as the proof.
>
> (The primary weight digest *is* genuinely verified here when the model binary is
> present — the existence-only shortcut applies to the signature file.)

---

## Step 5 — The flip (MY job — you do nothing)

When you confirm the key is present and the manifests are signed, I make a tiny
config change:

```toml
# services/policy_agent/config/default.toml
require_signed_manifest = true            # the 14B (already in place)
require_signed_draft_manifest = true      # the PA standalone/fallback draft (FUT-05 / #917)
# services/assistant_orchestrator/config/default.toml
require_signed_manifest = true            # the 14B (already in place)
require_signed_draft_manifest = true      # the shared-pipeline draft (FUT-05 / #107)
```

then merge it. From that boot onward, BlarAI will verify each manifest's
cryptographic signature at every startup — and fail closed if it has been tampered
with. Each change is reversible with one line.

There are **two** draft flags, one per config, because there are two draft loaders:
the launcher reads the **Assistant-Orchestrator** config for the shared-pipeline draft
it verifies, and the **Policy-Agent** config gates the draft the PA builds on its own
standalone/fallback path. The draft flags are **separate from the 14B flag on
purpose**: the 14B flag gates the authoritative model, and the 14B's protection is
never affected by the draft flags.

> **All four flags are now `true`** — this step is done. The rule described here
> ("each draft flag stays `false` until that draft's signature is actually
> present, because turning it on before the draft is signed would refuse to
> boot") was the *sequencing constraint while the drafts were unsigned*. Both
> drafts were signed and both flags flipped on 2026-07-18 (`78b17598`), so the
> constraint is satisfied and spent. If you read the sentence as "the draft flags
> are currently false", that is the pre-2026-07-18 world, not today's.

**You do not touch code. Wait for me to say "flip is in."**

---

## Step 6 — Verify the first signed boot (after the flip)

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m launcher
```

BlarAI should start cleanly. The startup log will include a line like:

```
Manifest signature verified: manifest=...\manifest.json key=BlarAI-Manifest-Signing
```

That line is the proof. **Paste me the startup log** (up to where the app window
opens). I will confirm the signature check passed and nothing fell back to
unsigned mode.

**If it stops with a FATAL / Fail-Closed message:** that is the safety net working,
not damage. Paste me the message and I will diagnose (usually "manifest updated
after signing — re-run Step 3"). This may take a cycle; that is normal for a
first signed boot.

---

## If you ever want to undo / reset

- **Back to unsigned mode:** I revert the one-line flip. Reversible anytime.
- **Model files changed:** re-run Step 2 (re-stage), then Step 3 (re-sign). The
  same key is reused; no new ceremony needed.
- **Stuck:** stop and paste me whatever you see. (Pre-ceremony framing: this said
  "nothing in this runbook can destroy data you care about." Stopping is still
  safe, but re-running the signing steps is not a no-op now that the ceremony has
  run — see the banner at the top.)
