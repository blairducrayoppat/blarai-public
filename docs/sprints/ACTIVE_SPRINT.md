---
title: Active Sprint Pointer
status: living
area: governance
---

# Active sprint — live pointer

**Last refresh (2026-07-30)** · Maintained by: the merging session that changes sprint
state — refresh the date line whenever this file's claims change; the doctrine-freshness
gate (`tests/security/test_doctrine_freshness.py`) fails if this file falls more than two
weeks behind the repository's latest commit.

> **A date bump is a claim.** This refresh RE-READ every assertion below rather than
> advancing the stamp — no sprint is running (no `/sprint-kickoff` has opened one),
> `DEC-11` is present in `docs/DECISION_REGISTER.md`, Vikunja is the live queue, and
> `docs/sprints/sprint_18/` still holds the five close-out files this file says it does.
> Stamping "fresh" on something only re-verified-by-assumption is the exact defect the
> 2026-07-30 instrument arc exists to remove (#1218, where a corpus manifest recorded a
> download date for artifacts that were merely re-checked). If you cannot re-read the
> claims, do not move the date.

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
