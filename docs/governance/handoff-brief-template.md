# Handoff-Brief Template (tracked)

**Authoritative discipline:** `C:\Users\mrbla\devplatform\CLAUDE.md`
§Context-Exhaustion-Handoff-Discipline. That prose is the SSOT; this file is
the **fill-in template** that makes the required structure hard to omit. It
exists because the doctrine's named "canonical cf-post-1 template" is no longer
on disk (untracked-by-convention → unrecoverable), and a freewritten brief
drifts from the spec (2026-07-05: a brief was authored as an "execute end to
end" runbook that never instructed the successor to run its comprehension gate
— the failure this template prevents).

**Live worked exemplars** (committed, doctrine-correct — read one before authoring):
`C:\Users\mrbla\devplatform\docs\guide-workstreams\fleet-functional-gap-closure\handoffs\guide-14-launch-brief.md`
(and `guide-12`/`guide-13` alongside it) — frontmatter + a real comprehension-gate
section + ≤6 first-action reads + the closing first-action order, all done right.

**The load-bearing rule this template enforces:** a handoff brief does NOT tell
the successor to start executing. It tells the successor to **ground itself on
disk, then present a comprehension gate (its understanding, in its own words,
of role / task / specifics / scope / risks / constraints) and WAIT for
User-Operator confirmation before any substantive or irreversible action.**
Authorization to *do the work* is never authorization to *skip the gate*. Do
not write "execute end to end," "do not add blocking gates," or any framing
that biases the successor past its comprehension gate — that is the specific
anti-pattern this template exists to kill.

Copy everything below the line into `docs/handoffs/<topic>-handoff-<YYYYMMDD>.md`
(that dir is gitignored — the brief is transient working-tree substrate) and
fill every section. Delete a section only if you can state why it does not apply.

---

```
---
artifact_type: handoff-brief
target_session: <fresh Claude Code session, this repo>
predecessor_session_anchor: <last commit SHA on main at author time>
status: HANDOFF
date: <YYYY-MM-DD>
---
```

# Handoff brief — <topic>

## SUCCESSOR: START HERE (do this before anything else)

Your first actions, in order — do NOT take any substantive or irreversible
action (edit, build that mutates state, external post, git write) until step 4
completes:

1. **First-action reads** (the ≤6 items in "Read list" below) — ground yourself
   in the actual on-disk state, not this brief's summary of it.
2. **Re-verify the anchor + references**: confirm `predecessor_session_anchor`
   is an ancestor of current `main` (`git log`), and spot-check the reference
   SHAs / paths below still resolve. A drifted anchor means the brief is stale —
   surface that instead of proceeding.
3. **Present your comprehension gate** to the User-Operator: in your OWN words
   (not a paraphrase of this brief), demonstrate substantive, substrate-grounded
   understanding of — your role, the immediate task, the work's specifics, scope
   remaining, the risks, and inherited constraints — and surface your own
   questions, ambiguities, and risk reads. Sized to the work (mature-not-minimal,
   no point-count cap). A recitation of this brief is NOT a comprehension gate;
   the gate must follow the reads and show real understanding.
4. **Wait for User-Operator confirmation** of the gate. Only then take the first
   substantive action. If the work involves an irreversible/external step
   (posting, deploying, sending), keep a short content readback at that step too.

## Read list (≤6 items — first-action reads)

- <path or ticket #1 — why it matters>
- <path #2>
- ... (≤6)

## Mission / goal

<what success looks like — the WHY and the end state, not just steps>

## Scope remaining + closure criteria

<what is done vs. not; how the successor knows it is finished>

## Risks

<the real risk surfaces — build may fail, external post is irreversible, data
mutation, model/hardware contention, etc. — each with the mitigation>

## Operational constraints (inherited)

<air-gap/privacy tier, never-destructive-git, feature-branches-only, pause-fleet
rules, LOCALAPPDATA isolation, record-hardware-results, journal obligation, etc.>

## Authorizations (be explicit + bounded)

<what the successor IS authorized to do without re-asking, and the exact
checkpoints that remain. NOTE: authorization to do the work does NOT authorize
skipping the comprehension gate. Never phrase an authorization as "skip the
gate" / "execute end to end" / "add no blocking gates".>

## Memory / subagent / substrate pointers

<recall memories to load, subagents to resume, templates/SSOT docs to consult>

## Reference SHAs + anchors (cold-start verification)

<commit SHAs, ticket numbers, evidence artifact paths the successor re-verifies>

## Predecessor state at author time

<what was true when this was written: gate status, app up/down, HEAD, what is
posted vs. drafted vs. dormant — so the successor can detect drift>
```
