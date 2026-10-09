---
title: Rotating the audit signing key
status: live
area: security
maintainer: Lead Architect (operator), with a Claude session driving the commands
---

# Rotating the audit signing key

**Plain summary: BlarAI signs every entry in its audit logs so you can prove none
of them was altered. If that signing key ever has to change, the old entries
still need the old key to check them. This procedure changes the key without
making the old entries unreadable — and without BlarAI deciding, wrongly, that
someone tampered with your logs.**

## When you need this

- The audit signing key is suspected of being compromised.
- The TPM is being re-provisioned, or the machine is being rebuilt.
- BlarAI refuses to start and the message contains `[key_mismatch]`.

You do **not** need this for the routine segment rotation the audit log does on
its own. That is a different thing that shares a word: it closes a full log file
and starts a new one, and it never changes a key. If a message mentions a
segment or a `.jsonl.gz` file, it is not this procedure.

## Step 0 — which chain?

BlarAI keeps **three separate audit chains**, and each rotates on its own:

| Chain | File | Where |
|---|---|---|
| Policy Agent adjudications | `adjudication_audit.jsonl` | the Policy Agent's **service** folder |
| Knowledge ingestion | `ingest_audit.jsonl` | `%LOCALAPPDATA%\BlarAI\audit` |
| Tool and egress verdicts | `verdict_audit.jsonl` | `%LOCALAPPDATA%\BlarAI\audit` |

If the key is suspected of being compromised, **every chain that exists must be
rotated.** They share one signing key today, so rotating one leaves the others
still signing with the suspect key.

See what is actually present — and whether it verifies — with one command:

```powershell
python -m shared.security.verify_audit_chain
```

It reports all three chains by name, including any that do not exist yet, and
changes nothing. See `docs/runbooks/verify_audit_record.md`.

This replaces the directory listing that used to be here. That listing globbed
`%LOCALAPPDATA%\BlarAI\audit` only, so it could never show the Policy Agent's
chain — the one the table directly above says lives somewhere else.

## Before you start

- **Nothing is deleted by this procedure, and you should not delete anything
  either.** Entries signed by the retired key can only be checked with that key.
  Deleting it destroys your ability to prove those entries are genuine — the
  same practical outcome as losing the log.
- BlarAI should not be running.
- You will need an elevated PowerShell session (the TPM requires it).

## Step 1 — see what would happen, changing nothing

If exactly one chain is present, the command finds it by itself. Otherwise pass
`--audit-log` with the full path: the script refuses to guess, because rotating
the wrong chain cannot be undone.

```powershell
cd C:\Users\mrbla\BlarAI
.\.venv\Scripts\python.exe -m shared.security.rotate_audit_key --new-key BlarAI-Audit-Signing-Key-v2 --dry-run
```

Expect:

```
OK   chain verifies under its current key (BlarAI-Audit-Signing-Key-v1).
DRY RUN: would provision 'BlarAI-Audit-Signing-Key-v2', append a bridge record
signed by 'BlarAI-Audit-Signing-Key-v1', and record the new key in the history.
Nothing was changed.
```

**If the first line is a REFUSED instead**, stop. The log does not verify as it
stands, and rotating now would sign a new entry into a chain whose integrity is
already in question — afterwards nobody could tell which problem came first. The
message names the fault class and what to do about it.

## Step 2 — rotate

```powershell
.\.venv\Scripts\python.exe -m shared.security.rotate_audit_key --new-key BlarAI-Audit-Signing-Key-v2
```

Expect every line to begin `OK`, ending with:

```
OK   the chain verifies ACROSS the rotation.

KEEP THE RETIRED KEY 'BlarAI-Audit-Signing-Key-v1'. ...
```

Then repeat for every other chain Step 0 listed, using the **same** new key name
and `--audit-log` to name each one.

Use a **new** name each time you rotate (`-v3`, `-v4`, …). Re-using a retired
name is refused: it makes the order of keys ambiguous for anything checking the
chain.

## Step 3 — confirm, and do it twice

Start BlarAI normally, **use it briefly so something gets written to the logs,
then stop it and start it once more.**

The second start is the one that matters. An earlier version of this feature
passed the first start and failed the second: new entries were being signed with
the *retired* key and appended after the entry announcing the new one, so the
first start — with nothing yet written after that entry — looked fine. **Both
starts verifying is the confirmation.**

## What the procedure changed

| Where | What |
|---|---|
| The TPM | A new signing key. **The old one is still there and stays there.** |
| The audit log | One new entry recording the change, signed by the **old** key. That entry is what lets anything checking the log cross from the old key to the new one. |
| `<chain-name>-keys.json` | The list of keys **that one chain** has used, oldest first. Each chain has its own. |

That last file is a convenience, not a security boundary: it says where to start
checking and which keys this chain is allowed to have used. The order is proven
by the signatures themselves, and every key has to exist on this machine's TPM.
Editing the file cannot make a forged log look genuine — it can only make a
genuine log fail to check, which shows up immediately as a refusal to start.

## If something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `No audit chain found under ...` | The chain you want is elsewhere — most likely the Policy Agent's, which lives under its service folder. | Pass `--audit-log` with the full path. |
| `More than one audit chain is present` | Working as intended: it will not guess. | Pass `--audit-log` to name one, then repeat for the others. |
| `REFUSED: the chain does not verify as it stands` | The log has a pre-existing problem. | Do not rotate. A `[tamper]` means preserve the file for investigation; a `[key_mismatch]` means a key changed without being recorded, or the history names a key no longer on this TPM. |
| `REFUSED: 'X' is already the current signing key` | Nothing to do. | Choose a new key name. |
| `FAILED: the rotated chain does not verify` | The bridge entry was written but verification afterwards failed. | Do not run it again. Preserve the log and the key history; both keys still exist, so nothing is lost. |
| BlarAI will not start, `[key_mismatch]` | The history may name a key this machine no longer has. | The refusal names the key. It must be restored; it cannot be regenerated. |

## Related

- `shared/security/rotate_audit_key.py` — the ceremony this runbook drives.
- `shared/security/audit_key_history.py` — the per-chain key-order file and why
  it is a hint rather than a trust root.
- `tests/security/test_audit_key_rotation.py` — the regression locks, including
  the three-boot check that the first version of this feature would have failed.
- `docs/runbooks/at_rest_encryption_ceremony.md` — a **different** key. That one
  encrypts stored content; this one signs audit entries.
