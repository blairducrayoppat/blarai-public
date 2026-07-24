---
artifact_type: handoff-brief
target_session: fresh Claude Code session, this repo (P5 author session)
predecessor_session_anchor: af296b77
status: HANDOFF
date: 2026-07-19
---

# Author brief — P5: The novice was the best instrument in the lab (flagship)

Committed program artifact (LA amendment 2, 2026-07-19).

## SUCCESSOR: START HERE

Do NOT edit / build-that-mutates-state / post / git-write until step 4 completes.

1. **Read** the ≤6 first-action reads below — ground on live disk/Vikunja, not this brief's summary.
2. **Verify anchors (machine-checked, not by eye)**: run
   `python scripts/verify_handoff_brief.py docs/research/publication-program/author-briefs/P5-author-brief.md`.
   Non-zero exit ⇒ stale brief ⇒ surface it, do not proceed.
3. **Comprehension gate** to the User-Operator: the FULL `CLAUDE.md` `<comprehension_gate>`
   section list, in your OWN words — substantive and substrate-grounded, sized to the work,
   surfacing your own assumptions, ambiguities, questions, and risk reads. A recitation of
   this brief is NOT a gate.
4. **WAIT for User-Operator confirmation.** Only then act. Irreversible/external steps
   are read back at that step — only the single LA-approved action.

## Read list (≤6, first-action)

- `docs/research/publication-program/README.md` — program instruction + §0 standards
- `docs/research/publication-program/AUTHOR_KIT.md` — working rules; §B pass; §F disclosure (ACTIVE — and see the IAPP carve-out in Mission); §G voice (the self-congratulation tightrope)
- `docs/research/publication-program/novelty-survey/P5-verdict.md` — your verdict: the related-work map (Bainbridge → Green → Vaccaro → Dhanorkar), the six binding conditions, venue mechanics
- `docs/research/publication-program/ROADMAP.md` §5 — the LA's ceremony decisions
- `docs/BUILD_JOURNAL_ANTHOLOGY.md` — the collaboration reading path = your catch-catalog's verbatim source
- Vikunja #962 (your ticket; epic #956) — live state + LA comments; VERIFIED_FACTS.md is implied standing context

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

Write the flagship governance case study: a documented, longitudinal existence proof
that a non-technical, rigor-literate human governance layer repeatedly caught failure
classes automated verification structurally could not — every catch a dated, citable
record. WHY: the AIGP-portfolio centerpiece; the piece the whole credibility ladder
was sequenced to support. **Timing constraint: publishes AFTER P1–P3 exist to link
to** — check the epic before gating; if P1–P3 aren't live yet, this brief is early and
you surface that instead of proceeding. **Authorship carve-out (Decision a): the IAPP
variant (800–1,200 words, pitch-first) is authored BY THE LA HIMSELF, by hand** — your
role there is at most research support he asks for, never drafting; IAPP bars
AI-drafted content without prior written consent.

## Scope remaining + closure criteria

- **In:** deep novelty pass (§I) incl. re-checking whether a documented
  novice-as-oversight case has appeared since 2026-07-19 → harvest the catch-catalog
  VERBATIM from the anthology/archives (each catch: date, his words as recorded, what
  it caught, the citation) → outline → the long-form draft → §B pass → panel → revise
  → LA ceremony.
- **The six binding conditions (survey; all verifiable at review):** (1) engage Green
  2022 + Vaccaro 2024 head-on as serious, partly-correct positions the case QUALIFIES;
  (2) existence-claim scoping — never a rate without a denominator; (3) "counter-example
  to oversight-efficacy pessimism," NEVER "refutes automation bias"; (4) every catch =
  verbatim DOCUMENTED-EVENT; (5) credit Lakhani/Einstellung/Schwartz — novelty is the
  case, not the idea; (6) position explicitly against Dhanorkar 2026.
- **Watch-list mechanics (calendar, don't act):** AI CHAOS! 2027 CFP unannounced —
  watch; FAccT 2027 abstract deadline 2026-10-27 (stretch; LA decides IF a submission
  ever happens).
- **Closure:** panel zero-reds + dispositions → LA ceremony → only the approved
  action. #962 closes when the LA declares P5 done or kills it.
- **Deferred/blocked:** none at brief time.

## Risks

- **Survivorship (deadliest):** catches without misses invites the Green critique
  verbatim. Existence-claim scoping or a real denominator — no third option.
- **Strawmanning the literature (AIGP-specific integrity hazard):** Green, Skitka,
  Bainbridge are respected in the exact certification world this feeds — represent
  them fairly even where they cut against the piece.
- **Self-congratulation tightrope:** the fleet is drafting a piece about its own
  operator's governance — keep interpretation clinical; let the documented catches
  carry it (AUTHOR_KIT §G).
- **Sense-bridge at LessWrong:** their "oversight" = alignment; ours = engineering
  governance — bridge explicitly or be misread.
- **Privacy:** the catch-catalog includes security incidents — every catch passes §D;
  his words only as actually recorded in the journal.

## Operational constraints (inherited)

CLAUDE.md binds: never-destructive-git · feature-branches-only · no `git add -A` ·
LOCALAPPDATA-redirect for pytest · journal fragment for the ship. Program layer:
README §0; AUTHOR_KIT §§A–J.

## Authorizations (explicit + bounded)

After YOUR gate: research, harvest, outline, draft (the long-form ONLY — not the IAPP
variant), panel, revise — autonomously. NO posting/submitting/commenting/account
actions without the LA's per-piece approval of that single named action. Venue set
FIXED per ROADMAP §5c (home base · LessWrong; IAPP + workshops later per Decisions
a/c); Reddit NOT approved.

## Memory / subagent / substrate pointers

Memories: `user_openvino_upstream_contributor` (who he is) ·
`feedback_no_commendations` (no praise sections — applies doubly to a piece ABOUT
him) · `feedback_research_human_readable_reports`. SSOT: program files; panel spec
README §4; the anthology's collaboration path. Pacing: Decision d = two threads; P5
starts only after P1–P3 are live.

## Reference SHAs + anchors (cold-start verification)

Phase 0 foundation bd06c6e6 · survey pack 05f40842 (land on main via the Phase-0 merge).

```anchors
# type   | value      | label                                  | derivation (count rows only)
sha      | af296b77   | predecessor_session_anchor (Phase-0 fork point)
path     | docs/research/publication-program/README.md | canonical program instruction
path     | docs/research/publication-program/AUTHOR_KIT.md | working rules + rubric + active disclosure
path     | docs/research/publication-program/novelty-survey/P5-verdict.md | this piece's survey verdict + six conditions
path     | docs/BUILD_JOURNAL_ANTHOLOGY.md | catch-catalog verbatim source (collaboration path)
count    | 7          | novelty-survey verdicts committed      | ls docs/research/publication-program/novelty-survey/*.md 2>/dev/null | wc -l
ticket   | #962       | this piece's ticket
ticket   | #956       | program epic
```

## Predecessor state at author time

Phase 0 complete; LA ceremony 2026-07-19: disclosure=full-transparency (§F ACTIVE)
with the IAPP hand-authored carve-out, home base=GitHub Pages-for-now (domain possible
in weeks), venues per ROADMAP §5c, pacing=2 threads, P1–P6 keep / P7 park. Nothing
posted anywhere. App DOWN at handoff. Main HEAD at brief authoring: af296b77 (pre-merge).
