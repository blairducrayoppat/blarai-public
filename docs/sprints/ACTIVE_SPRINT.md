---
title: Active Sprint Pointer
status: living
area: governance
---

# Active sprint — live pointer

**Last refresh (2026-07-19)** · Maintained by: the merging session that changes sprint
state — refresh the date line whenever this file's claims change; the doctrine-freshness
gate (`tests/security/test_doctrine_freshness.py`) fails if this file falls more than two
weeks behind the repository's latest commit.

**Current state: no sprint cadence is running.** The old sprint-paperwork world (design
visions, completion reports, gap reports, the retired fleet role that maintained this
file) is RETIRED — see DEC-11 in `docs/DECISION_REGISTER.md`. Work flows continuously:
**Vikunja (http://localhost:3456) is the live queue**, worktree builders and headless
dispatch execute, and every ship is an atomic merge + ticket + journal motion per
`CLAUDE.md`.

When a named sprint IS running (opened via `/sprint-kickoff`), this file points at it:
sprint number, theme, ticket cluster, and `docs/sprints/sprint_N/kickoff-brief.md`.

**History:** sprints 8–17 (+ this file's own pre-2026-07-19 body, which froze mid-June
asserting a two-sprints-stale world) live in [`docs/archive/sprints/`](../archive/sprints/)
— see its [INDEX.md](../archive/sprints/INDEX.md). `sprint_18/` remains in place pending
another session's in-flight close-out files. `_templates/` stays live.
