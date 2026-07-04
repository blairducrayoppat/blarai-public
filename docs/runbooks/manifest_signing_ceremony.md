# Manifest Signing Ceremony Runbook — locking the model weights to this machine

> **For the Lead Architect (non-developer-friendly).** Sprint 16, Stream B, FUT-04.
> This ceremony provisions the 4th TPM key (`BlarAI-Manifest-Signing`) and signs
> the weight-integrity manifest so BlarAI can verify — cryptographically — that
> its model files have not been tampered with between boots.
>
> **Stakes right now: very low.** The signing key is new and protecting nothing
> until you run this ceremony. If you need to redo a step, nothing is lost.
>
> **This ceremony is BATCHED** — the Orchestrator will drive it line-by-line in a
> later session alongside any other pending ceremonies (e.g. Sprint 17 #615),
> keeping your hands-on time to a single sitting. When that session arrives, this
> runbook is the script.

---

## The golden rules (read once)

1. **One command at a time.** Run a step, then paste me what it printed. I will
   confirm before you go on.
2. **These commands print only PUBLIC info** (key fingerprints, file hashes) —
   safe to paste to me. There is no secret output in this ceremony.
3. **You never edit code.** The flip to `require_signed_manifest = true` is my
   job (a tiny config change I make and merge); you run the ceremony commands.
4. **Stop anytime.** Nothing here is irreversible with no data at stake.
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
lines say `[ OK ]`. The line that will say `[ FAIL ]` is:

```
  [ FAIL ]  Manifest signing key           — NOT FOUND
```

That is expected — we create it in Step 2. If the **TPM sealer / signer** lines say
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

## Step 3 — Create the manifest-signing key and sign the manifest

This creates a new key **inside** your security chip and immediately signs the
manifest file you have on disk. The private key never leaves the chip. Safe to
re-run (idempotent — does nothing if the key already exists and just re-signs).

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m shared.security.provision_manifest_signing_key
```

**What you will see:**

```
Manifest signing-key provisioning ceremony (FUT-04 / ADR-018)
  TPM key name       : BlarAI-Manifest-Signing
  TPM key status     : created
  manifest signed    : ...\manifest.json
  signature written  : ...\manifest.json.sig
  public key written : ...\manifest.json.pub
  SHA-256 (SPKI DER) : <64 hex characters — your trust anchor>
  date (UTC)         : 2026-...
Done. Record the SHA-256 fingerprint above as the trust anchor.
...
NEXT: after verifying the signature on-chip, flip `require_signed_manifest = true`
```

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

---

## Step 5 — The flip (MY job — you do nothing)

When you confirm the key is present and the manifest is signed, I make a tiny
config change:

```toml
require_signed_manifest = true
```

in both service configs, then merge it. From that boot onward, BlarAI will verify
the manifest's cryptographic signature at every startup — and fail closed if it
has been tampered with. The change is reversible with one line.

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
- **Stuck:** stop and paste me whatever you see. Nothing in this runbook can
  destroy data you care about.
