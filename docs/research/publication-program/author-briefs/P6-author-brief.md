---
artifact_type: handoff-brief
target_session: fresh Claude Code session, this repo (P6 author session)
predecessor_session_anchor: af296b77
status: HANDOFF
date: 2026-07-19
---

# Author brief — P6: One laptop, night-shift fleet (governance-led hub)

Committed program artifact (LA amendment 2, 2026-07-19).

## SUCCESSOR: START HERE

Do NOT edit / build-that-mutates-state / post / git-write until step 4 completes.

1. **Read** the ≤6 first-action reads below — ground on live disk/Vikunja, not this brief's summary.
2. **Verify anchors (machine-checked, not by eye)**: run
   `python scripts/verify_handoff_brief.py docs/research/publication-program/author-briefs/P6-author-brief.md`.
   Non-zero exit ⇒ stale brief ⇒ surface it, do not proceed.
3. **Comprehension gate** to the User-Operator: the FULL `CLAUDE.md` `<comprehension_gate>`
   section list, in your OWN words — substantive and substrate-grounded, sized to the work,
   surfacing your own assumptions, ambiguities, questions, and risk reads. A recitation of
   this brief is NOT a gate.
4. **WAIT for User-Operator confirmation.** Only then act. Irreversible/external steps
   are read back at that step — only the single LA-approved action.

## Read list (≤6, first-action)

- `docs/research/publication-program/README.md` — program instruction + §0 standards
- `docs/research/publication-program/AUTHOR_KIT.md` — working rules; §D privacy screen + §E framing (your two hardest sections); §F disclosure (ACTIVE — for this piece the disclosure IS part of the story)
- `docs/research/publication-program/novelty-survey/P6-verdict.md` — your verdict: the saturation map, the combinatorial-novelty finding, Show-HN disqualification, venue mechanics
- `docs/research/publication-program/ROADMAP.md` §5 — the LA's ceremony decisions
- `docs/research/publication-program/VERIFIED_FACTS.md` — fact sheet (hardware spec = the only device detail that prints)
- Vikunja #963 (your ticket; epic #956) — live state + LA comments

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

Write the accessible front door: the warm-register narrative of a non-technical
person's private, local, security-first AI system — built by a governed AI fleet —
that routes readers to the substantive pieces. WHY: general reach; the hub that makes
the rest of the portfolio findable. **Timing: publishes LAST** — its whole design is
links to P1–P5; check the epic and surface early arrival instead of proceeding.

## Scope remaining + closure criteria

- **In:** freshness re-check of the saturation map (the genre moves) → outline →
  draft → §B pass → panel → revise → LA ceremony.
- **Binding shape (survey, mandatory reshape):** LEAD with governance + the identity
  split (dev fleet ≠ the private product) + governed-autonomy-with-documented-failures.
  NEVER lead with "my local AI setup" or "agents work while I sleep" — the two most
  saturated framings in the genre; include the honest "this genre is crowded, here is
  what is different" beat; route substance to the other pieces instead of re-arguing
  it. The ordinary-priced laptop is a strength — use it (the genre's critics call out
  six-thousand-euro rigs).
- **Register-specific privacy rule (survey risk 3):** the overnight story is told
  WITHOUT printing a real daily schedule or routine-level detail; public handle +
  published hardware spec only; no home-setup specifics beyond the laptop itself.
- **Framing doctrine (elevated in this register):** the warm voice reaches for "my
  little AI / toy / prototype / nearly done" — ALL forbidden. "Personal research
  project" / "long-term local AI system." Honest about limits and costs; governed
  autonomy, never unattended magic. Disclosure prominent — it IS the story.
- **Closure:** panel zero-reds + dispositions → LA ceremony → only the approved
  action. #963 closes when the LA declares P6 done or kills it.
- **Deferred/blocked:** none at brief time.

## Risks

- **Combinatorial-novelty fragility (highest):** if it reads as "another local-LLM
  post" or "another agent-army post," it dies on arrival — the reshape is the defense.
- **Show HN:** DISQUALIFIED on HN's own rules (nothing runnable; narratives
  off-topic) — normal link submission only. A future Show HN exists only if the
  project ever ships something readers can run; that would be a new LA decision.
- **XDA-class outlets:** no guest posts (their own pages) — pickup only; never pitch.
- **Autonomy overclaim / hype backlash:** sell the governance and the documented
  failures — the honesty is the differentiator.
- **Credibility of a non-technical byline on expert venues:** put verifiable substance
  up front (the dataset, the merged PR, the public mirrors) via links.

## Operational constraints (inherited)

CLAUDE.md binds: never-destructive-git · feature-branches-only · no `git add -A` ·
LOCALAPPDATA-redirect for pytest · journal fragment for the ship. Program layer:
README §0; AUTHOR_KIT §§A–J.

## Authorizations (explicit + bounded)

After YOUR gate: research, outline, draft, panel, revise — autonomously. NO
posting/submitting/commenting/account actions without the LA's per-piece approval of
that single named action. Venue set FIXED per ROADMAP §5c (home base · HN normal
link); Reddit NOT approved (and its reported undisclosed-AI ban is un-verified —
in-browser read required if ever revisited).

## Memory / subagent / substrate pointers

Memories: `feedback_blarai_public_framing_no_prototype_label` ·
`user_device_schedule_overnight_window` (context you must NOT print — the schedule is
private) · `feedback_soften_certainty_in_public_posts`. SSOT: program files; panel
spec README §4. Pacing: Decision d = two threads; P6 takes the last slot.

## Reference SHAs + anchors (cold-start verification)

Phase 0 foundation bd06c6e6 · survey pack 05f40842 (land on main via the Phase-0 merge).

```anchors
# type   | value      | label                                  | derivation (count rows only)
sha      | af296b77   | predecessor_session_anchor (Phase-0 fork point)
path     | docs/research/publication-program/README.md | canonical program instruction
path     | docs/research/publication-program/AUTHOR_KIT.md | working rules + rubric + active disclosure
path     | docs/research/publication-program/VERIFIED_FACTS.md | checked fact sheet (printable hardware spec)
path     | docs/research/publication-program/novelty-survey/P6-verdict.md | this piece's survey verdict + reshape
count    | 7          | novelty-survey verdicts committed      | ls docs/research/publication-program/novelty-survey/*.md 2>/dev/null | wc -l
ticket   | #963       | this piece's ticket
ticket   | #956       | program epic
```

## Predecessor state at author time

Phase 0 complete; LA ceremony 2026-07-19: disclosure=full-transparency (§F ACTIVE),
home base=GitHub Pages-for-now (domain possible in weeks — migration-friendly
permalinks), venues per ROADMAP §5c, pacing=2 threads, P1–P6 keep / P7 park. Nothing
posted anywhere. App DOWN at handoff. Main HEAD at brief authoring: af296b77 (pre-merge).
