---
title: Sprint 19 Kickoff Brief — Close the trust-spine gaps
status: living
area: governance
---

# Sprint 19 — Close the trust-spine gaps

**Opened 2026-09-17, 22:30 EDT, off `main` at `12f64b7a`.** Confirmed by the LA the same
evening with one correction to the order, recorded below.

The specification for this sprint is not this file. It is
[`docs/sprints/trust-spine-gap-closure-brief-2026-09-17.md`](../trust-spine-gap-closure-brief-2026-09-17.md)
for the packet, and **each ticket's DESCRIPTION** for its own work. This file records what
was agreed at the kickoff and nothing that already has a durable home.

---

## The goal

Eight tickets closing the distance between what BlarAI's trust spine **claims** and what it
**does**. An approval that binds to a tool's name but not to the arguments that execute
(#1541); two live adjudication doors that leave only an application log line (#1542); a
tamper-evidence check with no production caller (#1543); and the supporting work that makes
those three mean something.

Claim-register rows 27, 28 and 29 name gaps A, B and D. There is no Gap C ticket — three of
four survived triage.

## The order

```
1543 → 1545 → 1541 → 1547 → 1542 → 1544 → 1546 → 1548
```

**This differs from the execution brief's table, and the brief is the one that is wrong.**
The brief and #1548's sequencing line both place #1547 after #1542. Three surfaces say
otherwise, the earliest being the design both tickets cite:

> *"Item 3 is a separate read-only session and should run first, because its answer might add
> a field to item 1."*
> — `docs/research/acs-vocabulary-adoption-design-2026-09-16.md:123`; item 3 is the
> deny-mid-stream trace (#1547), item 1 is wiring both doors to `AuditLog` (#1542).

#1547's own description carries the heading *"Why it comes before #1542"*, and #1542 depends
on a settled field set. Running the trace second risks adding a field to a shipped receipt
schema and reopening the canonical-bytes question — the most expensive stop condition on the
list. The trace is read-only and cheap, so the swap costs nothing. LA correction, 2026-09-17.

`docs/ROADMAP.md` does not rank these tickets; its own 2026-09-16 refresh note says *"Nothing
below was re-ranked"* and these postdate that order. The order above is the LA's.

## The cluster

| # | What it closes | Ends as |
|---|---|---|
| 1543 | Gap D — `AuditLog.verify()` has no production caller | Code + locks, LIVE |
| 1545 | CAR gains category, systems touched, reversibility, target | Design note **then fields + locks**, LIVE |
| 1541 | Gap A — approval binds to the re-derived canonical hash | Code + locks, LIVE |
| 1547 | Deny-mid-stream persistence trace | Read-only finding on the ticket |
| 1542 | Gap B — signed receipts at both doors, denials included | Code + locks, LIVE |
| 1544 | Coverage disclosure as an Auditability Card | Documentation |
| 1546 | Confidentiality axis on provenance | **Design note only** — activation is the LA's |
| 1548 | Simulate-first as a fourth route outcome | Code + locks, **merges DORMANT** |

#1545 and #1546 end differently and the distinction is deliberate: #1545 ships its fields and
their regression locks; #1546 stops at the design, because switching on a refusal that could
block legitimate egress is a quality and posture question, and it is the LA's to take when a
second egress scope opens.

## Scope

**In:** this repository; Vikunja project 3; these eight tickets.

**Out, named so it stays out:**

- `C:\Users\mrbla\governator` — the #1549 product track, scrapped by LA decision 2026-09-17.
  The repository and its sixteen tickets on Vikunja project 14 still exist. Do not work in it,
  do not delete it, do not carry anything out of it. Its disposition is the LA's.
- **#1567 and #1568** (`curate_knowledge`, `organise_userdata`) — approved, dormant-merge, and
  a **separate arc**. Not started until these eight are closed.
- **#1566** — `CLAUDE.md` consolidation. See the budget note below; the stale 23:00 line
  belongs to it, not to this sprint.
- The **August journal rotation** and its monthly retrospective.

**Also touched:** `docs/sprints/ACTIVE_SPRINT.md` (pointed here), and `CLAUDE.md`'s
`<status_snapshot>` at merge clusters.

## Constraints carried from the kickoff

1. **`CLAUDE.md` has 369 bytes of headroom** — 47,631 LF-normalised against a hard 48,000,
   measured 2026-09-17. The status snapshot is **replaced, never appended**, and its gate
   figure syncs with `docs/TEST_GOVERNANCE.md` §1 in the same commit. The budget is not
   raised; #1566 is explicit on that.
2. **The primary checkout is not clean.** On 2026-09-17 it sits on `main` with three untracked
   documents belonging to other sessions. Explicit paths only, never `git add -A`, and
   `git branch --show-current` is checked before every commit made there.
3. **The battery is indefinitely disabled.** Every `BlarAI-Battery-*` scheduled task reads
   `Disabled`; nothing fires at 23:00 and nothing contends with gate runs or merges. The only
   unattended job on the night of 2026-09-17 is `BlarAI System Backup` at 23:30.
   `CLAUDE.md` still asserts the 23:00 window opens unconditionally — that line is stale, is
   not acted on, and is not fixed here.

## Stop conditions — return to the LA before finishing

- **#1543** — the real audit chains on this machine do not verify today. A finding, not a bug
  to fix quietly.
- **#1547** — a denied turn does leave partial assistant text in the encrypted store. A
  privacy posture finding.
- **#1542** — new receipt fields change the canonical bytes of existing records and break
  `verify()` over old segments. A migration decision.
- **#1544** — a surface turns out to be observer-only that nobody had said was observer-only.
  The coder-fleet dispatch path is the one most likely to produce this.
- **#1548** — a `generate_image` preview cannot be produced without evicting the resident 14B.
  The ticket then ships with zero declaring tools: the designed outcome, not a failure, and
  worth telling him.
- Two failed fixes on the same defect: bank the dead end on the ticket, put fresh context on it.

## Who decides what

**The LA's:** the order (exercised at kickoff); #1548's go-live ceremony; #1546's eventual
activation; any of the five stop conditions if one fires.

**The session's, not returned for:** every implementation choice, the CAR field set, the
receipt schema, test strategy, fast-versus-full verify at boot, branch and merge sequencing.

## Execution notes

The headless coding fleet in `agentic-setup` is **not** used for this work: it is the single
adjudication door, the approval binding and the signed audit chain, where every ticket ships a
lock proving it blocks and a toggle-test proving the probe fails when the lock is off.
Parallelism comes from in-session subagents and worktree builders on disjoint limbs, and from
the `adversarial-reviewer` agent before each merge, since the author is never the verifier.
Dispatch quiet is re-checked immediately before each merge rather than assumed from an earlier
reading.

The devplatform fleet is untouched; that repository is being sunset.
