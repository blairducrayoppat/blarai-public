# Runbook: At-Rest Encryption Ceremony (ADR-025, Sprint 14)

**Scope:** BlarAI at-rest encryption (`substrate.db` + `sessions.db`) + the tamper-evident audit stream.
**Modules:** `shared/security/provision_dek_keystore.py`, `tpm_sealer.py`, `tpm_signer.py`, `dek_envelope.py`
**Status:** READY — run **once** on the deployment host, before the first production-posture boot with real data.
**Who runs it:** the Lead Architect (you), on the real machine, in a private terminal. **Not an agent** — see §0.

---

## 0. Why YOU run this, not Claude (READ FIRST)

This ceremony prints your **offline recovery key once**. Anything run through a Claude session — including
the `! <command>` prefix — captures terminal output into the session transcript on disk, which would create
a permanent **digital copy of your break-glass key** and defeat its entire "shown once, never written to
disk" guarantee. So:

- Run every command below in a **normal terminal window** (Windows Terminal / PowerShell) — **NOT** inside a
  Claude session, and **NOT** with the `!` prefix.
- Before you start, have a way to record the recovery key **off the machine**: paper + pen, or a USB drive
  you store in a safe. **Not** a file on this PC. **Not** a cloud note.

Claude does everything *around* the ceremony (pre-flight checks, and all verification afterward — none of
which touches the secret). The one command that prints keys, and writing the recovery key down, are yours.

---

## 1. What this provisions, and why each matters

| Artifact | What it is | Why it matters |
|---|---|---|
| **RSA seal key** `BlarAI-DEKSeal` | A key created *inside* the TPM chip; its private half never leaves the chip. | Wraps (locks) your data-encryption key so only *this* machine's chip can unlock it day-to-day. |
| **DEK keystore** (`dek_keystore.json`) | The data-encryption key, wrapped twice (by the chip + by your recovery key) and written to disk. | This is what the app loads at boot to decrypt your data. It never contains the key in the clear. |
| **Offline recovery key** | A 64-character code, shown once. | Your **break-glass**: the *only* way to recover your data if the chip ever dies or you change machines. |
| **Audit signing key** `BlarAI-Audit-Signing-Key-v1` | A separate TPM key for the tamper-evident audit log. | Lets the Policy Agent's decision log be cryptographically verified (and the PA refuses to start without it in production). |

One data key, wrapped two ways, shared by both databases (ADR-025 §2.1). The chip is the everyday lock; the
recovery key is the spare you keep in a safe.

---

## 2. Prerequisites

- The **real deployment machine** (Intel Lunar Lake) with its **TPM 2.0** chip. The ceremony refuses to run
  without a real TPM — there is no software fallback (fail-closed).
- The BlarAI **virtual environment** active (the same one you run BlarAI from).
- If a command fails with a permissions/CNG error, run the terminal **as Administrator** and retry.
- Your **off-box recovery-key recording method** ready (paper / USB) — see §0.

---

## 3. The ceremony — one command

In a normal terminal, from the repo root, with the venv active:

```
python -m shared.security.provision_dek_keystore
```

You will see, in order:

1. A banner, then **Step 1 of 3 — RSA seal key**: confirms `BlarAI-DEKSeal` was created (or already existed).
2. **Step 2 of 3 — DEK envelope + keystore**: confirms the keystore path, then prints a loud block:

   ```
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
   !  RECOVERY KEY — SHOWN ONCE — STORE THIS OFF THE MACHINE
   ...
     Recovery key (hex):  <64 hex characters>
   ```

   → **STOP HERE. Write the recovery key down off-box NOW** (paper / USB → safe). It is shown only once and
   is never written to disk. If you lose it *and* the chip later dies, the data is unrecoverable.

3. **Step 2b — round-trip verification**: confirms the data key unlocks via **both** the chip path and the
   recovery key (both must say PASS, and both must produce the same key).
4. **Step 3 of 3 — audit signing key**: confirms `BlarAI-Audit-Signing-Key-v1`.
5. **NEXT STEPS**: it prints the exact `BLARAI_DEK_KEYSTORE=<path>` value to set.

Then set that environment variable persistently (so the services find the keystore every boot):

```
setx BLARAI_DEK_KEYSTORE "<the path it printed>"
```

(`setx` writes a user-level env var; open a new terminal afterward for it to take effect. The path must
match exactly what the ceremony printed.)

---

## 4. Existing dev data — wipe fresh, or migrate (your call)

Your current `substrate.db` / `sessions.db` hold only disposable build-phase dev/test data — there is no real
sensitive data yet (this is *why* the sprint was well-timed, not urgent).

- **Recommended — start fresh, born-encrypted:** delete the old dev databases; the stores create new,
  encrypted databases on first run. Every byte of real data is then encrypted from its first write, with no
  plaintext ever having existed.
- **Or — migrate the existing dev rows in place:** the encryption modules include an idempotent migration
  (encrypt-in-place + a `VACUUM` scrub that leaves no plaintext in freed pages). This is engineering
  correctness / a real-shaped test, not a rescue (there's nothing sensitive to rescue). Tell Claude if you
  want this run; it's a one-off and does not touch the recovery key.

Either path is valid — the choice is yours.

---

## 5. Production-posture live-verify — the "it's real" check (the only thing that counts for #598)

With `BLARAI_DEK_KEYSTORE` set, start BlarAI in **production posture** (dev-mode OFF — the same way you run
it for real, not a dev/test launch). Then these confirm encryption is genuinely live — **Claude runs these
checks for you; none touches the recovery key:**

- The databases are **ciphertext at rest** — a raw read of `substrate_chunks.text/.embedding/.source` and
  `turns.content` / `sessions.title` shows no readable text, vectors, or filenames.
- Normal use still works — retrieval returns the right results, sessions show correct history (decrypt-on-read).
- The **audit chain verifies** with the TPM key.
- The **recovery path round-trips** (the automated dead-chip test, or a `--recover` rehearsal on a *copy* of
  the keystore).

Only this production-posture pass counts as "works" for the #598 gate — dev-mode green never does.

---

## 6. Recovery on a dead / replaced chip (your break-glass)

If the chip dies or you migrate to new hardware, on the new machine:

```
python -m shared.security.provision_dek_keystore --recover
```

It prompts for your offline recovery key (hidden input — it will not appear on screen), unlocks the data key
via the recovery path **only** (it does not rely on the old chip), re-seals it to the **new** chip, rewrites
the keystore, and prints a **NEW recovery key**. → **Store the new key off-box; the old one is now invalid.**
Then set `BLARAI_DEK_KEYSTORE` and restart the services.

---

## 7. Rotation (`--rotate`) — caution

```
python -m shared.security.provision_dek_keystore --rotate
```

Replaces the keystore with a **fresh** data key. This **destroys the current data key** — all existing
encrypted data becomes unreadable unless you have already migrated / re-encrypted it. The ceremony refuses to
overwrite an existing keystore *without* this flag, precisely to prevent an accidental data-orphaning. Only
use it before real data exists, or as part of a deliberate re-encryption.

---

## 8. Fail-closed behaviour (what refuses, and when)

| Condition | Behaviour |
|---|---|
| No usable TPM 2.0 on the host | Ceremony refuses to run; no key created, no keystore written. |
| Keystore already exists, no `--rotate` | Ceremony refuses (guards the live data key). |
| Keystore missing / unreadable in production | The stores **refuse to open** — no plaintext fallback, ever. |
| Audit TPM key OR audit-log path missing in production | The Policy Agent **refuses to start** (a PA with no audit trail is a governance hole). |
| Wrong recovery key during `--recover` | Fails closed (authentication check); nothing is overwritten with a bad key. |

There is no soft-degradation path for the encrypted data: the system runs with the real keys, or it refuses.

---

## 9. What gets recorded afterward (trust anchor)

After the ceremony, Claude records the **key fingerprints** (not the keys, not the recovery key) into
ADR-025 §5 and a `docs/ledger/` entry — the date, the key names, and a SHA-256 of each public key, so the
trust root is documented. The recovery key itself is never recorded anywhere digital.

---

## 10. The other production keys (for a full production boot)

This runbook covers the Sprint-14 ceremony (the DEK seal key + the audit key). A full production posture also
uses two keys provisioned by their own (pre-existing) ceremonies — run these too if they have not been done
on this host:

- **Policy-Agent JWT signing key** (ADR-021): `python -m shared.security.provision_signing_key`
- **Model-weight manifest signing key** (ADR-018, FUT-04): `python -m shared.security.provision_manifest_signing_key`

---

*Authored Sprint 14 (ADR-025 criterion #6). The ceremony tooling is `provision_dek_keystore.py`; the
encryption design is ADR-025; the campaign gate is Vikunja #598.*
