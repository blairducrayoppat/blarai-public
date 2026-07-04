# Active State Refresh — Deterministic Procedure

**Procedure home**: `docs/runbooks/active_state_refresh.md`
**Companion helper** (optional): `tools/active_state_refresh.ps1`
**Owner cadence**: Co-Lead Architect at Sprint Kickoff Phase 3 transition AND Sprint Close (SCR-authoring).
**First procedural invocation**: Sprint 11 SCR (DEC-15 SCR cadence; the SCR's §Active State subsection is the first piece of authored text downstream of this procedure).

---

## SS1 — Purpose

The `CLAUDE.md` §Active State block is the single human-readable snapshot of fleet state — current sprint id, current pytest baseline, current HEAD reference, current Vikunja tracking task. It is the data the LA, EA Code wakes, SDO reviews, and the SCR/SWAGR pipeline all read as their orientation pass.

**Drift recurrence (3-sprint chain)**. The §Active State block has drifted from operational reality in three consecutive sprints:

- **Sprint 8 SWAGR gap #5** (2026-04-24) — §Active State referenced Sprint 7 figures after Sprint 8 closed; pytest baseline stale by ~226 tests.
- **Sprint 9 SWAGR gap #4** (2026-04-24) — recurrence; §Active State referenced Sprint 8 SCR after Sprint 9 closed.
- **Sprint 10 SWAGR §15.3** (2026-05-11) — third recurrence; §Active State pointed at Sprint 9 figures, sprint id, and HEAD reference well after Sprint 10 was OPERATIONAL.

**Structural cause** (Sprint 11 SDV §3). The drift pattern is **polarity**, not vigilance: when a Co-Lead at sprint-close opens `CLAUDE.md`, sees the existing §Active State block, and edits it in place, the prior text is a magnet — sprint numbers tick by one, but pytest figures, HEAD pointers, and sprint-name strings are copied unchanged because they "look filled in." The block stays nominally fresh while drifting against measurement.

**Polarity inversion (this procedure's core rule)**. Every refresh STARTS with live computation against the four sources below and ENDS with a writeback to `CLAUDE.md`. Prior `CLAUDE.md` text is a **reference for section ordering and phrasing convention only** — NOT a data source. If a refresh begins by reading the existing §Active State block, the polarity is wrong; restart.

## SS2 — Inputs

Four data sources, all read live:

- **BlarAI repo** (`C:\Users\mrbla\BlarAI`): pytest baseline + main HEAD reference.
- **Vikunja MCP server** (`localhost:3456`): active sprint tracking task + label set + sprint id.
- **Roster file** (`C:\Users\mrbla\BlarAI\docs\active_tasks.yaml`): sprint_id, task_id, continuation_xml path.
- **Prior `CLAUDE.md` §Active State** (READ-ONLY, **for shape/phrasing reference only**): used to confirm bullet ordering and section conventions; never copied as a data source.

The procedure DOES NOT read ACTIVE_SPRINT.md (Co-Lead authors that file on transition; reading it here would re-introduce the copy-prior-text polarity).

## SS3 — Live-computation steps (executed in order)

### (a) Pytest pass/skip baseline

```powershell
cd C:\Users\mrbla\BlarAI
.\.venv\Scripts\pytest shared/ services/ launcher/ --tb=no -q 2>&1 | Select-Object -Last 5
```

Extract the `<N> passed, <M> skipped` line verbatim. The number of `passed` and `skipped` are the only fields that enter §Active State; warnings, deselected, xfail, and timing are noted in the SCR but not in §Active State.

**Discipline**: if pytest fails to collect (`ERROR` in last 5 lines), STOP. Do not refresh §Active State from a partial run — investigate the collection error first (typically a stale conftest or missing dependency).

### (b) BlarAI main HEAD reference

```powershell
git -C C:\Users\mrbla\BlarAI log --oneline -3 main
```

The §Active State bullet on HEAD reference does NOT pin a hash — per current convention, the bullet reminds the reader that `git log --oneline main` is authoritative. The three-line output captured here lives in the SCR (which IS hash-pinned), not in §Active State. The live capture is still required: it confirms the procedure was actually run against main (not against a feature branch).

**Discipline**: if `git branch --show-current` returns anything other than `main` on the BlarAI working tree, STOP. The refresh runs against main only.

### (c) Vikunja sprint state via MCP

```
mcp__vikunja__get_task(<tracking_task_id from active_tasks.yaml>)
mcp__vikunja__list_tasks(project_id=3, filter_by="done", filter_value="false")
```

Extract:

- Sprint name (from the tracking task `title`).
- Current label set (especially Gate:* labels — they signal where the sprint is in the gate cycle).
- The set of OTHER active tasks in project 3, which establishes whether parallel sprints are in flight.

**Discipline**: if the MCP server is unreachable, STOP. Do NOT route via Vikunja webUI screenshots as a substitute — the procedure's value depends on machine-readable inputs. Either bring the MCP server up or pause the refresh.

### (d) Roster file read

```powershell
Get-Content C:\Users\mrbla\BlarAI\docs\active_tasks.yaml
```

Extract per-entry: `task_id`, `sprint_id`, `continuation_xml`. The roster confirms the same sprint_id that Vikunja returned, and surfaces any parallel-sprint entries (multiple `active_tasks` rows).

**Discipline**: if the YAML schema has changed (new required fields, unexpected nesting), STOP and surface to the LA. The procedure does not silently adapt to schema drift.

### (e) Writeback target

The ONLY target file is `C:\Users\mrbla\BlarAI\CLAUDE.md` §Active State. The procedure:

- DOES NOT write `ACTIVE_SPRINT.md` (Co-Lead-only, via Phase 3 transition step 8 of the Co-Lead Architect wake template).
- DOES NOT write `active_tasks.yaml` (Co-Lead-only, via roster-transition path).
- DOES NOT write the SCR (Co-Lead authors SCR §Active State by INVOKING this procedure first — the procedure's output is the SCR's reference).

The writeback is a hand-edit by the Co-Lead. The helper script (see SS3.5) prints the prospective block to stdout; the Co-Lead pastes it into `CLAUDE.md` over the prior §Active State block. No tooling writes `CLAUDE.md` automatically — the human-in-the-loop step is a feature, not a friction.

### SS3.5 — Helper script (optional)

`tools/active_state_refresh.ps1` automates steps (a) through (d) and prints the assembled §Active State block to stdout. Usage:

```powershell
cd C:\Users\mrbla\BlarAI
.\tools\active_state_refresh.ps1
```

The script is fail-closed: any failed step (pytest collection error, git not on main, Vikunja unreachable, YAML schema unexpected) exits non-zero and prints WHICH step failed. It does NOT modify `CLAUDE.md` — the writeback remains the Co-Lead's hand-edit.

## SS4 — Worked example (Sprint 11 kickoff state, captured 2026-05-12 UTC)

The values below are from an actual run against the Sprint 11 kickoff state. A Co-Lead re-running the procedure against the same snapshot (worktree at commit `60d59eb`, devplatform at `0dbd4a6`, Vikunja state at 2026-05-12 ~14:00 UTC) obtains the same shape of output (numbers may drift if Vikunja state or git state advances).

### (a) pytest baseline

```
$ .\.venv\Scripts\pytest shared/ services/ launcher/ --tb=no -q | Select-Object -Last 5
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================ 1001 passed, 2 skipped, 2 warnings in 46.78s =================
```

Extracted: `1001 passed, 2 skipped`. (Captured 2026-05-12 ~13:55 UTC, BlarAI HEAD `60d59eb`.)

### (b) BlarAI main HEAD log

```
$ git -C C:\Users\mrbla\BlarAI log --oneline -3 main
60d59eb [agent:sdo] report: comprehension-review APPROVED for Task 11 Sprint 11 EA-2
5079d5f [agent:co_lead] report: completion (Phase 2 auto-merge) for Task 11 Sprint 11 EA-1
3cb441e [agent:co_lead] archive EA queue prompt after merge -- feature/p5-task11-ea1-ledger
```

Extracted: HEAD is `60d59eb`. The §Active State bullet still reads "prefer `git log --oneline main` over pinning a hash" — the captured HEAD lives in the SCR, not the §Active State block itself.

### (c) Vikunja sprint state

```
$ mcp__vikunja__get_task(410)
{
  "id": 410,
  "title": "Task 11: Process-Hygiene Backlog Paydown Sprint",
  "labels": ["Active", "Architecture", "Documentation", "Gate:Approved"],
  ...
}

$ mcp__vikunja__list_tasks(project_id=3, filter_by="done", filter_value="false")
[ {"id": 410, "title": "Task 11: Process-Hygiene Backlog Paydown Sprint", ...} ]
```

Extracted: Sprint 11 ACTIVE; tracking task #410; sprint name "Process-Hygiene Backlog Paydown"; no parallel sprint in project 3 at this snapshot.

### (d) Roster file

```
$ Get-Content C:\Users\mrbla\BlarAI\docs\active_tasks.yaml
schema_version: 1
active_tasks:
  - task_id: 410
    sprint_id: 11
    continuation_xml: docs/P5_TASK11_SDO_CONTINUATION_v1.0.xml
    started: '2026-05-11'
    pause_after: false
pause_after_current: false
```

Extracted: sprint_id=11; task_id=410; continuation `docs/P5_TASK11_SDO_CONTINUATION_v1.0.xml`. Confirms (c) — no parallel-sprint asymmetry.

## SS5 — Resulting §Active State block (illustration only — lives inside this runbook, not in CLAUDE.md)

The block below is what the Co-Lead would paste over the existing `CLAUDE.md` §Active State block at Sprint 11 SCR cadence, assembled from the SS4 worked-example values. It is shown here for illustration; the writeback is a separate hand-edit.

```markdown
## Active State

- **HEAD reference**: prefer `git log --oneline main` over pinning a hash here — the BlarAI main HEAD advances each merge and pinning it in doctrine becomes stale within a sprint.
- **Sprint state**: Sprint 11 is ACTIVE (Vikunja tracking task #410, sprint_id 11 per `docs/active_tasks.yaml`). Sprints 7, 8, 9, and 10 are COMPLETE. SDV at `docs/sprints/sprint_11/strategic_design_vision.md`.
- **Test baseline** (post-Sprint-11 SCR): **1001 passed, 2 skipped** on `pytest shared/ services/ launcher/`. Substitute the live value at SCR cadence.
- **Task 7** (Test Quality Audit): COMPLETE — closed by Sprint 8.
- **Domain 6** (MCP Ecosystem): COMPLETE.
- **LEDGER**: per-file (Q1-1 format) in `docs/ledger/`; monolithic `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` frozen at Entry 52.
- **Open issues**: ISS-1, ISS-2, ISS-3. (Refresh open-issue set against Vikunja at each invocation.)
```

The block is constructed in this order every time, regardless of which numbers drifted — the order is part of the convention, not a data point.

## SS6 — Failure modes and remediation

- **(a) pytest collection error**. STOP. Do not refresh from stale numbers; investigate the collection error first. Common causes: stale `conftest.py`, missing optional dependency, recent file rename not picked up by pytest cache. Remediation: clear `.pytest_cache/`, re-run; if persistent, file an Issue.
- **(b) HEAD on a non-main branch**. STOP. Refresh only against `main`. If you are in a per-EA worktree, switch to the BlarAI main working tree for the refresh; the procedure is a sprint-close / sprint-kickoff cadence, not an in-flight EA task.
- **(c) Vikunja MCP server unreachable**. STOP. Webui-screenshot fallback is forbidden as a substitute data source (procedure relies on machine-readable input). Restart Vikunja per `CLAUDE.md` §Task Tracking — Vikunja (MCP) → "Vikunja Server" section, then resume.
- **(d) `active_tasks.yaml` schema unexpected** (new required field, unexpected nesting, schema_version bumped). STOP. The procedure does not silently adapt to schema drift; surface to the LA and amend the procedure + helper script in lock-step.
- **(e) Multiple active sprints (parallel-sprint state, DEC-16)**. The procedure emits one §Active State block; multi-sprint state is captured by listing both sprint IDs and tracking task numbers in the "Sprint state" bullet. Example: "Sprints 11 and 12 are ACTIVE in parallel (Vikunja #410 and #<next>); SDVs at `docs/sprints/sprint_11/strategic_design_vision.md` and `docs/sprints/sprint_12/strategic_design_vision.md`." Do NOT collapse to a single sprint — the asymmetry is the load-bearing signal.
- **(f) Drift detected on completion** (helper script's output disagrees with the existing §Active State block on numbers, not just on phrasing). This is the SUCCESS case for this procedure: paste the new block over the old. The procedure exists precisely because that disagreement is the steady-state.

## SS7 — Audit hooks

The Co-Lead Architect wake template (`devplatform/docs/scheduled/wake_templates/co_lead_architect.md`) references this procedure at TWO cadences:

- **Sprint Kickoff (Phase 3 transition)** — when a new sprint enters the roster, the Co-Lead invokes this procedure as part of the kickoff continuation to populate §Active State with the new sprint's data.
- **Sprint Close (Phase 3 Step 0, SCR authoring)** — before composing the SCR §Active State subsection, the Co-Lead invokes this procedure to produce the live snapshot the SCR is written against.

Sprint 11 SCR is the first invocation. The recurring 3-sprint drift loop terminates there.
