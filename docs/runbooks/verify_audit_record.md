---
title: Checking your own audit record
status: live
area: security
maintainer: Lead Architect (operator), with a Claude session driving the commands
---

# Checking your own audit record

**Plain summary: BlarAI keeps signed, tamper-evident records of what it has done
— every policy decision, every document taken in, every tool call and outbound
request. This is how you check those records yourself, whenever you want, in one
command. It changes nothing. It is safe to run at any time, as often as you
like.**

## Why this exists

The whole point of a tamper-evident record is that its owner can check it rather
than take someone's word for it.

Until 2026-09-20 you could not. The only code that walked a record from end to
end did it as step 1 of a key-rotation ceremony — so the only way to ask "is my
record intact?" was to begin changing a signing key. That is an absurd thing to
have to do to answer a question, and it meant the question mostly went unasked.

## The command

```powershell
python -m shared.security.verify_audit_chain
```

Run it from the BlarAI folder. It takes a few seconds on a small record and
longer on a large one, because it deliberately takes the slow route (see
"What it actually does" below).

To check one specific file — for example a copy you preserved somewhere else:

```powershell
python -m shared.security.verify_audit_chain --audit-log <path to the file>
```

## What you will see

It reports every chain by name, whether or not it exists, and leads with the
answer:

```
ALL CLEAR. 1 audit chain verified completely, record by record.

Policy Agent adjudications -- ABSENT
  file:   ...\services\policy_agent\data\audit\adjudication_audit.jsonl
  holds:  every policy decision this system has made
  No such file. This chain has never been written on this machine.

Knowledge ingestion -- VERIFIED
  file:   C:\Users\...\AppData\Local\BlarAI\audit\ingest_audit.jsonl
  holds:  every document taken into the knowledge bank
  size:   33 records
  period: 2026-06-11T07:07:00+00:00 to 2026-07-13T00:52:44+00:00
  Every record still on disk was re-hashed and its signature re-checked.
  This chain has no sealed archive files.
```

### The outcomes, and what each one means

| Outcome | What it means | What to do |
|---|---|---|
| **VERIFIED** | Every record still on disk was re-hashed and its signature re-checked. Nothing was altered. | Nothing. |
| **ABSENT** | No such file. This chain has never been written on this machine. | Nothing, unless you expected records here — in which case the service that writes them has not run, or is writing somewhere else. |
| **TAMPER** | The contents were **altered on disk**. This is a tamper finding, not a configuration problem. | **Preserve the file.** Do not delete it, do not regenerate it, and do not run a key rotation on it. The command names which record broke. |
| **KEY_MISMATCH** | Every record hash is intact and only the *signatures* fail — the verifying key is not the signing key. | If the key was rotated or re-provisioned, run the rotation ceremony (`docs/runbooks/audit_key_rotation.md`). If it was **not**, treat this as a forgery attempt. |
| **VERIFIED, BUT NOT COMPLETE** | Everything still on disk verified — but retention has removed part of the history. What remains is genuine; it is not the whole record. The `GONE:` line says how many records are missing. | Nothing, if you turned retention on deliberately. If you did not, find out who did. |
| **UNCHECKABLE** | The command could not check this chain at all. This is **not** a clean bill of health. | Read the reason it gives. The two common ones are a retired key that is no longer on the chip (restore it — a retired audit key must never be deleted) and a chain signed with a development key, which means those records were written by a service running in development mode. |
| **UNREADABLE** | The file could not be parsed as an audit chain at all. | Preserve it. A file that cannot be parsed is not the same as one that fails to verify, and the difference matters to whoever investigates. |

**ABSENT is reported on purpose.** A command that silently skipped the chains it
could not find would let "no adjudication record exists yet" be read as "the
adjudication record is fine". Those are different statements.

**UNCHECKABLE is not a pass.** If any chain comes back UNCHECKABLE, the headline
says NOT FULLY CHECKED rather than ALL CLEAR, and the command exits non-zero.

### Exit codes, if you are scripting it

| Code | Meaning |
|---|---|
| 0 | Every chain present verified. |
| 3 | A chain FAILED — tamper or key mismatch. |
| 4 | A chain could not be checked at all. Not a pass. |
| 2 | The command could not run — including `--audit-log` naming a file that is not there. A missing named file is **not** a pass. |

## What it actually does

- **Walks every record, the slow way.** The routine check that runs when BlarAI
  starts trusts a signed summary of the older, archived parts of the record and
  does not reopen them. This command does not: it unpacks every archive file and
  re-checks every record inside. It exists for the person who does not want to
  trust a summary.

  **Honest limit**, because it would be easy to oversell this: an independent
  review tried to find a tampered archive that the routine check would pass and
  this command would catch, and could not. Editing a record inside an archive
  also breaks the fingerprint the signed summary holds for that file, so the
  routine check catches it too. The exhaustive walk is a second, independent
  way of reaching the same answer — worth having, and worth the extra seconds,
  but not a stronger check with a known case of its own.
- **Checks all three chains, not just the easy two.** The three live in two
  different places, and the routine discovery helper only looks in one of them —
  it does not find the Policy Agent's. This command looks in both.
- **Changes nothing.** It never writes, never creates a directory, and never
  touches a key. It opens every chain read-only, which also means it works on a
  preserved copy held on read-only media.
- **Never picks the verifying key from the record's own claim.** A forged chain
  can claim anything about which key signed it. The key comes from the chain's
  own key history.

## The three chains

| Chain | File | Where |
|---|---|---|
| Policy Agent adjudications | `adjudication_audit.jsonl` | the Policy Agent's **service** folder |
| Knowledge ingestion | `ingest_audit.jsonl` | `%LOCALAPPDATA%\BlarAI\audit` |
| Tool and egress verdicts | `verdict_audit.jsonl` | `%LOCALAPPDATA%\BlarAI\audit` |

You do not need to know this to run the command — it reports all three by name,
including the ones that do not exist. It is here because the rotation runbook
needs the same table.

## See also

- `docs/runbooks/audit_key_rotation.md` — changing the signing key, which is a
  ceremony and a different thing entirely.
- `shared/security/verify_audit_chain.py` — the command.
