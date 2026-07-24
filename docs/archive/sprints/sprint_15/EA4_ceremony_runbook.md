# EA-4 Ceremony Runbook — turning on BlarAI's production security

> **For the Lead Architect (non-developer-friendly).** Sprint 15, EA-4. This is the
> hands-on session that switches BlarAI from "practice mode" (dev) to "real security
> mode" (production) for the first time, on your actual machine.
>
> **Stakes right now: very low.** You confirmed there is no real data in BlarAI yet.
> So the worst realistic outcome is "we re-do a step" — nothing can be lost. Treat this
> as a relaxed dress rehearsal: you learn the drill once, safely, before any real data exists.
>
> **Dated note (2026-06-06):** performed at zero-data-stakes. *If you ever re-run this with
> real data present, back up `dek_keystore.json` + the data folder first.* Today that's not needed.

---

## The golden rules (read once)

1. **One command at a time.** Run a step, then paste me what it printed. I'll confirm before you go on.
2. **These commands print only PUBLIC info** (checkmarks, public fingerprints, file hashes, boot logs) — safe to paste to me. **The one exception is flagged in BIG letters** in Step 2b; if you hit that, you do NOT paste its output.
3. **You never edit code.** When we reach the "flip," that's my job — I make a tiny code change and merge it; you do nothing for that step.
4. **Stop anytime.** If anything looks off, stop and tell me. Nothing here is irreversible, and with no data there is nothing to lose.
5. **If a step fails:** don't retry blindly — paste me the error. Most failures here are fail-closed (the system refuses to start), which is *safe*, not damage.

---

## Step 0 — Open your terminal (one-time setup each session)

1. Click Start, type **PowerShell**, right-click **Windows PowerShell** → **Run as administrator**, and click Yes.
   *(Administrator is needed because the final boot starts the Hyper-V virtual machine. Running everything in the admin window keeps the security-chip keys consistent between provisioning and boot.)*
2. In that black window, paste this and press Enter (it moves into the project folder):

   ```
   cd C:\Users\mrbla\blarai
   ```

For every command below, use the project's own Python by pasting the **full path** shown — you don't need to "activate" anything.

---

## Step 1 — Look before touching (read-only check)

This **changes nothing**. It just reports which security pieces are already in place.

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m shared.security.ceremony_preflight
```

**What you'll see** — a checklist. If Sprint 14 is intact, most lines say `[ OK ]`. The two that will likely say "NOT FOUND" are the **JWT signing key** and the **Production manifest** — that's expected; we create those in Steps 2 and 3. A healthy "almost ready" result looks like the all-OK version of this:

```
  [  OK  ]  TPM sealer (RSA-2048 OAEP)        — available
  [  OK  ]  TPM signer (ECDSA P-256)           — available
  [  OK  ]  DEK seal key                       — present (BlarAI-DEKSeal)
  [  OK  ]  Audit signing key                  — present (BlarAI-Audit-Signing-Key-v1)
  [ FAIL ]  JWT signing key                    — NOT FOUND   <- we fix this in Step 2
  [  OK  ]  DEK keystore file                  — present
  [ FAIL ]  Production manifest                — NOT FOUND   <- we fix this in Step 3
  RESULT:  NOT READY — 2 prerequisite(s) need attention.
```

**→ Paste me the whole checklist.** I'll tell you exactly which of the next steps you need (it adapts to what's already there). If the first two lines (TPM) say "NOT available," stop — that means the security chip isn't reachable, and we sort that out before anything else.

---

## Step 2 — Create the token-signing key (if Step 1 said it's missing)

This creates a new key *inside* your security chip and exports only its **public** half. The private half never leaves the chip. It's safe to re-run (does nothing if it already exists).

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m shared.security.provision_signing_key
```

**What you'll see:** a short report ending with a `SHA-256 (SPKI DER)` fingerprint and "Done." That fingerprint is **public** — safe to paste.

**→ Paste me the output.**

### Step 2b — ONLY if Step 1 said the DEK seal key / keystore is MISSING

If (and only if) Step 1 showed the **DEK seal key** or **DEK keystore** as NOT FOUND, the encryption keys from Sprint 14 aren't on this machine and we recreate them:

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m shared.security.provision_dek_keystore
```

> ⚠️ **READ THIS FIRST — this command is the ONE exception to the "paste me everything" rule.**
> It prints a **RECOVERY KEY** — a long secret shown **once**. **Do NOT paste it to me or anywhere online.**
> Copy it to a safe offline place (a password manager or a written note). Then paste me only the
> *rest* of the output (the part that is NOT the recovery key). With no real data yet this key
> protects nothing important *today*, but practice the habit now: treat it like a master password.

*(If Step 1 showed the DEK key/keystore as present, skip 2b entirely.)*

---

## Step 3 — Record your model's fingerprint (the manifest)

This computes a fingerprint (SHA-256) of your actual model files and writes the "known-good manifest" the production check compares against. Safe to re-run.

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m shared.models.stage_production_manifest
```

**What you'll see** (real example):

```
--- Step 2 of 3 — Compute SHA-256 digests ---
  openvino_model.bin
    SHA-256: 63df8d8aaef642825d18c363dfe4f267c1f90bd08da32bc40f1508644e7a44e3
--- Step 3 of 3 — Write manifest ---
  Manifest written : ...\manifest.json
  Manifest Staged Successfully
```

(These hashes are public — safe to paste.) **→ Paste me the output.**

---

## Step 4 — Re-run the check (confirm everything's green)

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m shared.security.ceremony_preflight
```

You're aiming for the all-`[ OK ]` version ending in:

```
  RESULT:  READY for production boot
           All prerequisites are present.
```

**→ Paste me the checklist.** When it says **READY**, tell me — that's my cue for Step 5.

---

## Step 5 — The flip (MY job — you do nothing)

When you confirm **READY**, I make a tiny, already-built-and-tested code change so BlarAI defaults to production mode, and I merge it. It's reversible with one line. You don't touch code; just wait for me to say "flip is in — go to Step 6."

*(After the flip, if you ever want practice/dev mode back, it's an explicit, loud opt-in — I'll show you the one environment-variable switch; you'll never have to edit code.)*

---

## Step 6 — First production boot (the real test)

This starts BlarAI in real-security mode for the first time.

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m launcher
```

**What you'll see:** the startup steps scroll by — Administrator confirmed, VM starting, and (new in production) **"Provisioning per-boot mTLS certificates ✓"**, then the services come up and the app window opens. If it reaches the app, the production cascade passed and signing is live.

**→ Paste me the startup log** (up to where the app window opens). I'll confirm the three things that prove success: signing went live, the per-boot certificate handshake used the freshly-minted CA, and nothing fell back to practice mode. Then you can close the app window.

**If it instead stops with a "FATAL … Fail-Closed" message:** that's the safety net working, not damage. Paste me the message and I'll tell you the one thing to fix (usually a missed earlier step) — then we retry. This may take a cycle or two; that's normal for a first real-hardware run.

---

## Step 7 — Second boot (proves daily use stays painless)

Run the exact same command again:

```
C:\Users\mrbla\blarai\.venv\Scripts\python.exe -m launcher
```

It should start cleanly with **zero** manual steps — that proves your everyday startup isn't burdened by the new security. **→ Paste me the log**, then close the app.

---

## Step 8 — Done (MY job)

Once both boots are confirmed, I record the result (the evidence that production posture works), close EA-4, and Sprint 15 is complete. I'll tell you plainly what's now live and what the air-gap gate (#598) still needs after this.

---

## If you ever want to undo / reset

- **Back to practice mode:** I revert the one-line flip (or you set the loud opt-in switch I'll show you). Reversible anytime.
- **Something's inconsistent:** because there's no data, the clean fix is "re-provision from scratch" — re-run Steps 2–3. Nothing is lost.
- **Stuck:** stop and paste me whatever you see. There is no command in this runbook that can destroy anything you care about.
