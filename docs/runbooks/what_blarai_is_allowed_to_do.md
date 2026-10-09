---
title: What BlarAI is allowed to do
status: live
area: governance
maintainer: Lead Architect (operator), with a Claude session driving the commands
---

# What BlarAI is allowed to do

**Plain summary: one command prints everything BlarAI is currently permitted to
do, in plain language — each capability, whether it is on, and for the one thing
that leaves this machine, exactly where it goes. It reads the live settings and
the live code every time you run it, so it cannot go stale. It changes nothing.**

## The command

```powershell
python -m shared.governance.permission_profile
```

Run it from the BlarAI folder. It is instant and completely safe — it decides
nothing, permits nothing, and writes nothing.

## Why this exists

Until 2026-09-20 there was no single place where you could read what BlarAI was
allowed to do. Answering it meant reading a settings file, a risk-tier table, a
rule engine and several runbooks, and knowing which of them outranked which.

That is a governance surface only its author can use, and its author is not the
one who owns the risk. This is the other half of the
[Auditability Card](../governance/auditability-card.md): that one discloses what
is *watched*, this one states what is *allowed*.

## What it will not do

**It is not a second gatekeeper.** It has no say in any decision. Every number
and every switch it shows is read, at the moment you run it, from the thing that
actually enforces it — the settings file the service itself reads, the list of
permitted addresses that actually refuses connections, the code that classifies
tools. If a setting changes, the next run says so without anyone remembering to
update anything.

This matters more than it sounds. A written-down summary of permissions is a
second copy of the answer, and a second thing to forget at a go-live ceremony.
There is no second copy here.

## The part worth reading twice

The last section of the output is headed **"Something it has never been told
about"**, and it answers the question that decides what a future capability is
allowed to do before anyone has classified it.

The comforting answer would be "it asks you first". **That is not what happens,
and the command says so plainly.** What actually happens, in the order the
controls actually fire:

1. BlarAI can only call a fixed list of named tools. Anything else it tries is
   refused **by name**, before any other check runs — you see "BlarAI does not
   provide that tool". This, not the risk rating, is what stops an unknown tool.
2. A tool that *is* on that list but that nobody has given a risk rating falls
   back to **DANGEROUS**, the most restricted rating rather than the least.
3. In any conversation that has taken in outside content — a web result, a
   document you added — such a tool is **refused outright**, with no way to wave
   it through.
4. **In any other conversation it would run.** The rules are written to catch
   known-bad actions, so an action no rule mentions draws no objection, and no
   objection is what proceeding looks like.

Point 4 is the one worth acting on, and it is why the command reports whether
there are any tools it can call that nobody has classified. Today there are
none — the callable list and the rated list are the same eight names.

**An earlier version of this page said something else**, and it was wrong in the
reassuring direction: it said such an action "goes to the Policy Agent, which
decides locally using the model". The model is never consulted on a tool call at
all. That claim is recorded here rather than quietly deleted, because it is the
kind of sentence that gets quoted back.

If the control that does the refusing is ever switched off — or if the fallback
rating is ever loosened to one that control does not catch — the command prints a
warning in place of the confident paragraph.

## Two settings that said something nothing enforced

Building this found two sections in the settings file that **nothing read**:
`[preemption]` and `[circuit_breaker]`. One of them stated a limit of 5 chained
tool calls where the real limit is 3 — a number in your own settings file that
was wrong in the reassuring direction, and that nothing would ever have
corrected, because nothing consulted it.

Both are gone. A test now fails if any new section appears in the settings file
that nothing reads, because a settings file you read is a governance surface: a
number in it that nothing enforces is a false statement about what the system
will do.

## See also

- [../governance/auditability-card.md](../governance/auditability-card.md) —
  what is recorded, and by which surface.
- [verify_audit_record.md](verify_audit_record.md) — checking that those records
  have not been altered.
- `shared/governance/permission_profile.py` — the command.
