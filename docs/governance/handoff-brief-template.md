# Handoff-Brief Template (tracked)

Discipline SSOT: `CLAUDE.md` `<context_handoff>` (self-contained). This file is the fill-in structure that a freewritten brief drifts from.

LOAD-BEARING RULE 1 — the GATE. A brief does NOT tell the successor to execute. It tells the successor to **ground on disk → present the FULL `CLAUDE.md` comprehension gate (all sections, own words) → WAIT for User-Operator confirmation** before any substantive or irreversible action. Doing-the-work authorization is NEVER gate-skip authorization.

LOAD-BEARING RULE 2 — the QUEUE. A brief hands over **the work queue**, never only the predecessor's in-flight threads. Those threads are a SUBSET of the successor's job, not the whole of it. The `## Work queue` section below is REQUIRED and must name the live board — **especially any ticket the predecessor's own ship just UNBLOCKED**, which is the most-missed class because the predecessor was busy shipping the thing that unblocked it. State in the brief that **Vikunja is the SSOT, not the brief**, and that the successor must read the board fresh and read ticket DESCRIPTIONS (not just comment tails — the description is the spec, comments are its history). A thread-only brief leaves the successor "finished" with a full board, which is exactly the idle queue `CLAUDE.md` `<autonomy>` forbids. *(2026-07-22: a brief handed over three in-flight threads and omitted the four tickets that night's own merge had unblocked; the User-Operator caught it, not the author.)*

LOAD-BEARING RULE 3 — RETRACTIONS. A brief must carry what this session got WRONG and corrected. A successor inherits your artifacts, not your corrections: a superseded claim in a **committed** commit message, a landed record, or a ticket comment reads as current fact to someone who was not in the room. The `## Retractions & superseded claims` section below is REQUIRED — write "none" if there genuinely were none, never omit it. *(2026-07-22: one session produced three retractions in a day, including a commit title on `main` whose headline its own later measurement withdrew; the record needed an explicit superseded banner because the successor would otherwise have read it as the finding.)* This is the journal's failures-stay-in discipline applied forward instead of backward.

ANTI-PATTERN (forbidden; the 2026-07-05 failure): never write "execute end to end", "do not add blocking gates", or any framing that biases the successor past its gate. Never pre-write the successor's gate points into a brief — the gate is the successor's own understanding, produced after its reads, not points to recite.

USE: copy everything below the `---` into `docs/handoffs/<topic>-handoff-<YYYYMMDD>.md`. **Date the filename.** This directory is gitignored, so a same-name brief overwrites its predecessor with NO history to recover it — the one place in this repo where an accidental overwrite is unrecoverable. (No collision has been observed; this is cheap insurance against an unrecoverable one, not a fix for a known failure.) Fill every section; delete one only with a stated reason. Keep the "BlarAI operational surface" block VERBATIM.

CORRECTION (2026-07-22, same day): commit `8dbb2164` justified the dated-filename rule by claiming undated names "collide and the older brief silently wins". **That failure was never observed** — the same-topic files it was inferred from are one session's successive states from a single day, and an overwrite would destroy the OLDER file, not preserve it. The rule stands on the verified reason above (this directory is gitignored, so an overwrite is unrecoverable). Recorded here because the commit message cannot be rewritten and would otherwise read as evidence.

REQUIRED — the ANCHORS block (machine-checked): every brief MUST carry a filled ```anchors block (in "Reference SHAs + anchors", schema below). It is the structural retirement of LESSONS.md lesson 14 ("a brief is a map, not the territory"): `scripts/verify_handoff_brief.py` re-derives every anchor against the live repo and fails loud on drift, so a successor never grounds on a stale fact instead of merely being told to re-check by hand. A brief with no valid ANCHORS block FAILS the verifier — leaving placeholders in it is the same as leaving it out. The successor runs the verifier at grounding step 2 (below); do not hand off without it green.

---

```
---
artifact_type: handoff-brief
target_session: <fresh Claude Code session, this repo>
predecessor_session_anchor: <main HEAD SHA at author time>
status: HANDOFF
date: <YYYY-MM-DD>
---
```

# Handoff brief — <topic>

## SUCCESSOR: START HERE

Do NOT edit / build-that-mutates-state / post / git-write until step 4 completes.

1. **Read** the ≤6 first-action reads below — ground on live disk/Vikunja, not this brief's summary.
2. **Verify anchors (machine-checked, not by eye)**: run `python scripts/verify_handoff_brief.py docs/handoffs/<this-brief>.md`. It re-derives every anchor in the ```anchors block (SHAs are ancestors of `main`, paths exist, live-state counts recount on disk, ticket refs well-formed) and exits non-zero on ANY drift. A non-zero exit ⇒ the brief is stale ⇒ surface it, do not proceed. (This replaces eyeball spot-checking — lesson 14's vigilance step is now enforced.)
3. **Comprehension gate** to the User-Operator: the FULL `CLAUDE.md` `<comprehension_gate>` section list (role & authority / context / goal / task + plan / scope / inherited constraints / risks + decision points / assumptions & ambiguities / open questions), in your OWN words — substantive and substrate-grounded (built from the reads in steps 1–2, not a paraphrase of this brief), mature-not-minimal, sized to the work, no point-count cap, surfacing your own questions, ambiguities, and risk reads. A recitation of this brief is NOT a gate — the gate follows the reads and shows real understanding.
4. **WAIT for User-Operator confirmation.** Only then act. For an irreversible/external step (post/deploy/send), read the content back at that step too.

## Read list (≤6, first-action)

<Six is a budget for the brief's OWN topic reads. The board read (`project_summary` + the queue below) is grounding, not one of the six — `CLAUDE.md` `<session_start_protocol>` already requires it of every session. Do not spend the budget re-listing standing doctrine either; name what is specific to THIS handoff.>

- <path or ticket #1 — why it matters>
- <#2> … (≤6)

## BlarAI operational surface — STANDING (keep verbatim; do this AUTONOMOUSLY, never ask)

> Same for every BlarAI session — copy verbatim; update only when the ops surface changes. Exists so a session NEVER stalls asking the User-Operator to start/stop BlarAI, the coder, or a dispatch.

**STANDING AUTHORIZATION (User-Operator):** you run ELEVATED (admin) with FULL authority to start/stop BlarAI, start/stop the coder (30B) and any dispatch, and start/stop/query the battery scheduled task — WITHOUT asking. **NEVER pause work to ask the User-Operator to start/stop any of these** (auto-memory: freely-start/stop-AO/launcher/GPU/builds; stop-doomed-runs-fast; execute-don't-stop-when-goal-clear). Only genuine `decision_boundary` items route to the User-Operator — a capability/quality/security-posture flip, a go-live ceremony, the #855 shadow graduation — NEVER routine process control.

**UP vs DOWN:** keep BlarAI DOWN for merges + the standing gate (clean-env: no live-app `:5001` skips, models present). UP only for a live surface (drive a chat, a validation dispatch).

**START** (elevated shell):
```powershell
Start-Process -FilePath "C:\Users\mrbla\BlarAI\.venv\Scripts\pythonw.exe" -ArgumentList '-m','launcher','--winui' -WorkingDirectory "C:\Users\mrbla\BlarAI"
```
- MUST be the venv-shim `pythonw` (bare/system pythonw dies silently — lacks `cryptography`); cwd = repo. Elevated is fine — the shim de-elevates the WinUI child (orphan-guarded).
- Confirm UP (~30–60 s, 14B cold-load): `:5001` listening (`Get-NetTCPConnection -LocalPort 5001 -State Listen`); `%LOCALAPPDATA%\BlarAI\launcher.log` shows "Minimal prompt-flow preflight passed ✓"; the "BlarAI" WinUI window exists.
- Not up? Read `%LOCALAPPDATA%\BlarAI\crash.log` (a launcher.log showing only "Cleanup: …" with no error ⇒ the reason is in crash.log). The WinUI window is a foreground grab — you ARE authorized to raise it without warning/asking (supersedes warn-before-screen-taking for autonomous operation).

**STOP** (kill the launcher tree — the orphan-guard Job Object kills the WinUI + backend children; the boot reconciler `shared/fleet/swap_state.py` converges any stranded swap on next start):
```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match '-m launcher' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```
Usually TWO matches (venv shim + real launcher) — kill both. `sessions.db` is born-encrypted + flushed ⇒ no data loss.

**CODER / DISPATCH (30B):** a dispatch manages its OWN swap — steps the 14B aside, loads the 30B coder, runs the plan-graph, restores the 14B + reports. Trigger via /dispatch or New-Project once BlarAI is up. Stop a doomed run yourself (never ask): reap the `run-fleet` + BOTH `swap_ops` drivers, then relaunch BlarAI (the reconciler cleans the stranded swap):
```powershell
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" | Where-Object { $_.CommandLine -match 'swap_ops|run.fleet' }
```

**BATTERY TASK (nightly ~23:00):** fires on its own — no action needed. You may `Get-`/`Start-`/`Stop-ScheduledTask` it (name via `Get-ScheduledTask | Where-Object { $_.TaskName -match 'blar|battery' }`). Overnight GPU work MUST run via the elevated scheduled task (a hand-launched console strands on UAC).

**PID liveness:** use `tasklist` / `Get-Process` — NEVER git-bash `kill -0` (false negatives on native Windows PIDs).

## Mission / goal

<end state + WHY, not steps. Frame it as DRIVING THE QUEUE — the in-flight threads are the top of it, not the whole of it. Do not write a mission that can be completed and then stopped.>

## Work queue (REQUIRED — Rule 2)

**Vikunja is the SSOT, not this brief.** State that explicitly here, tell the successor to run `project_summary` and read the board itself, and date this list as the snapshot it is.

Table the live items in suggested order, each with: state, and WHY it sits where it does. It is the successor's job to re-judge the order — say so.

- **Call out every ticket the predecessor's OWN ship just UNBLOCKED.** This is the most-missed class: a `blocked-by:` predicate that the handing-over session itself satisfied. Grep the board for predicates naming what you just merged.
- **Name the sequencing constraints that are easy to violate** — one-change-per-run instrument cadence, GPU contention, an LA ceremony that gates a flip, anything where doing two queued items together destroys attribution.
- **Read ticket DESCRIPTIONS, not comment tails** (a description is the build spec; comments are its history). *(Until 2026-07-23 there was a second, mechanical reason: the comment tool returned only the OLDEST 50, so a long ticket's newest state was invisible. Fixed in #1034 — devplatform `ed3db38`. The guidance stands on its own merits; the truncation no longer applies.)*

## Retractions & superseded claims (REQUIRED — Rule 3)

<What this session asserted and later withdrew, and WHERE the stale version still lives. "None" is a valid answer; omission is not. For each: the claim, what refuted it, and whether the stale form is still readable in a COMMITTED artifact (commit message, landed record, ticket comment) — because that is what a successor will hit without knowing it was corrected. If a committed artifact carries a superseded headline, say whether you added a superseded banner to it; if you did not, say why, so the successor can.>

## Scope remaining + closure criteria

<Per ITEM: done vs. not, and how the successor knows THAT ITEM is finished. The SESSION is not finished when they are — it returns to the queue above. Never write a closure criterion for the session as a whole.>

**Deferred/blocked — BOTH halves required:** each deferred/blocked item needs its durable record (ticket CURRENT-STATE) AND a queue placement (#859 / the Coordinator board) with an unblock predicate — list the queue entries here. Record without queue placement = a DROPPED item (LESSONS.md lesson 10: durability without distribution is half the job).

## Risks

<real risk surfaces — build-fail, irreversible post, data mutation, model/hardware contention — each with its mitigation>

## Operational constraints (inherited)

<cite the binding CLAUDE.md sections, don't restate: privacy tier, never-destructive-git, feature-branches-only, LOCALAPPDATA-redirect-for-pytest, hardware-results-recorded, journal obligation>

## Authorizations (explicit + bounded)

<TASK-specific: what the successor may do without re-asking + the exact remaining checkpoints. Process control — start/stop app/coder/dispatch/battery — is ALREADY granted by the STANDING block above; do not re-litigate it here. Never phrase any authorization as "skip the gate" / "execute end to end".>

**AUTHOR ≠ VERIFIER — state it explicitly when it binds.** If this session WROTE code that is still unreviewed, or wrote the fixes to findings against its own code, say so here in as many words: the successor must not be the one who signs it off, and a reviewer must never write the fix. A handoff is the easiest place for that separation to dissolve silently, because the branch looks finished and the next actor has no memory of who authored what. Name any test the author rewrote after a fix changed the design — that is the author-edits-tests-until-they-pass shape and it needs an independent eye, not a fresh assertion.

## Memory / subagent / substrate pointers

<memories to load, SSOT docs to consult.

For SUBAGENTS, state for EACH: its name, whether it is RUNNING or STOPPED at handoff, exactly how far it got, and what it still owed. A name alone is not a handoff — "resume `x`" tells the successor nothing about whether work is in flight, already delivered, or lost. Include any briefing lesson learned the hard way (e.g. an agent that did the work but never delivered a report, and what changed in the next brief to fix it) — that is reusable and expensive to rediscover.

Kill or hand over deliberately: leaving an agent running past a handoff means work landing in a session that no longer exists.>

## Reference SHAs + anchors (cold-start verification)

<Prose is optional; the ```anchors block below is REQUIRED and machine-checked by `scripts/verify_handoff_brief.py` (grounding step 2). Replace every `<...>` placeholder — a leftover placeholder FAILS the verifier. Rows are pipe-delimited: `<type> | <value> | <label> [| <derivation>]`.>

- `sha`    — a commit SHA (7-40 hex); verified to be an ancestor of `main`.
- `path`   — a repo-relative file/dir; verified to exist.
- `count`  — an integer live-state count; REQUIRES a 4th field, the shell command that re-derives it on disk (its output must equal the declared integer). **RUN your derivation before pasting it** — this template shipped a fragment-count example that counted `README.md` and would have propagated an off-by-one into every brief using it (found 2026-07-22). A derivation you have not executed is a guess with a shell prompt in front of it. This is the "carry the derivation inline so the successor re-derives instead of trusting" rule — use it for every volatile count/state you assert. The derivation must exit 0 even on a legitimately-zero count — use a `... | wc -l` pipeline (or append `|| true`); a bare `grep -c` exits non-zero on a zero match and would spuriously FAIL the brief.
- `ticket` — a `#NNN` reference; structural check only (an optional `--check-board` probe degrades to a warning, never fails). **Rule 2:** carry a row for every ticket THIS session's ship unblocked, in addition to the brief's own topic tickets — an unblocked item with no anchor row is the one a successor never opens.

```anchors
# type   | value                       | label                              | derivation (count rows only)
sha      | <main HEAD sha at author time> | predecessor_session_anchor
sha      | <merge sha you rely on>        | <what shipped in it>
path     | <docs/.../evidence-artifact>   | <why it matters>
path     | docs/TEST_GOVERNANCE.md        | live gate SSOT
count    | <N>                            | journal fragments awaiting fold    | ls docs/journal_fragments/*.md 2>/dev/null | grep -v README | wc -l
count    | <N>                            | highest lesson number in LESSONS.md      | grep -oE '^[0-9]+\.' LESSONS.md | tail -1 | tr -dc '0-9'
ticket   | <#NNN>                         | <the ticket this brief is about>
ticket   | <#NNN>                         | <a ticket THIS session's ship UNBLOCKED - Rule 2; one row each>
```

## Predecessor state at author time

<Structured, so the successor can detect DRIFT rather than infer it. Cover at minimum:

- **main HEAD** + which branch the tree is on, and every branch carrying unmerged work of yours (with its tip and why it is unmerged).
- **Gate figure AND when it was measured** — against which commit, and whether anything has changed since. "8749 measured before the last three fixes" is honest; "8749" alone invites a successor to copy a stale number into a doctrine surface.
- **App up/down**, live processes, scheduled jobs that will fire unattended (a nightly that owns the box from 23:00 is a constraint on the successor's plan, not trivia).
- **DORMANT vs LIVE for anything you touched** — explicitly, per `CLAUDE.md` `<context_handoff>`. "Nothing dormant flipped" is a sentence worth writing when true.
- **Whose uncommitted work is in the tree.** Name files carrying ANOTHER session's changes and say plainly not to stage them. This is where a careless `git add -A` does its damage, and the successor cannot tell your dirt from theirs.
- **Anything posted, sent, or deployed externally** — or "nothing posted externally", which is equally load-bearing.>
