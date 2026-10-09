---
title: Active Sprint Pointer
status: living
area: governance
---

# Active sprint — live pointer

**Last refresh (2026-10-02)** · Maintained by: the merging session that changes sprint
state — refresh the date line whenever this file's claims change; the doctrine-freshness
gate (`tests/security/test_doctrine_freshness.py`) fails if this file falls more than two
weeks behind the repository's latest commit, or if it exceeds its 4,000-byte budget.

> **This file REPLACES its contents; it never appends.** Prior refresh narratives live in git
> history. This refresh is a state change, not a re-read: the previous body said Sprint 19 was
> running, and the board says it is not.

## Current state: NO NAMED SPRINT IS OPEN

**Sprint 19 — "Close the trust-spine gaps"** (opened 2026-09-17, kickoff
[`sprint_19/kickoff-brief.md`](sprint_19/kickoff-brief.md)): every ticket of its cluster is
closed on the board — #1543, #1545, #1541, #1547, #1542, #1569, #1544, #1546, #1570, #1548,
plus the two tools it approved, #1567 and #1568 (closed 2026-09-18 to 2026-09-20, read from
Vikunja on 2026-10-02). `sprint_19/` holds only the kickoff brief: **no debrief file exists**,
and none is claimed here.

**What orders the work now:** [`docs/ROADMAP.md`](../ROADMAP.md) is THE ORDER; Vikunja
(http://localhost:3456) is the live queue. The offline reference-corpus programme (epic #1616,
retrieval epic #1648) is the largest open arc; its go-live bars and ceremony live on #1616's
description, not here.

A named sprint is a scoped cluster of Vikunja tickets with one kickoff gate at the front and
one debrief at the end, per DEC-11. The retired sprint-paperwork world (design visions,
completion reports, gap reports) stays retired. Every ship is an atomic merge + ticket +
journal motion per `CLAUDE.md`.

**History:** sprints 8–17 live in [`docs/archive/sprints/`](../archive/sprints/) — see its
[INDEX.md](../archive/sprints/INDEX.md). `sprint_18/` remains in place pending another
session's close-out files. `_templates/` stays live.
