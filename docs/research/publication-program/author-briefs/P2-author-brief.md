---
artifact_type: handoff-brief
target_session: fresh Claude Code session, this repo (P2 author session)
predecessor_session_anchor: af296b77
status: HANDOFF
date: 2026-07-19
---

# Author brief — P2: When two correct things collide (the specimen collection)

Committed program artifact (LA amendment 2, 2026-07-19).

## SUCCESSOR: START HERE

Do NOT edit / build-that-mutates-state / post / git-write until step 4 completes.

1. **Read** the ≤6 first-action reads below — ground on live disk/Vikunja, not this brief's summary.
2. **Verify anchors (machine-checked, not by eye)**: run
   `python scripts/verify_handoff_brief.py docs/research/publication-program/author-briefs/P2-author-brief.md`.
   Non-zero exit ⇒ stale brief ⇒ surface it, do not proceed.
3. **Comprehension gate** to the User-Operator: the FULL `CLAUDE.md` `<comprehension_gate>`
   section list, in your OWN words — substantive and substrate-grounded, sized to the work,
   surfacing your own assumptions, ambiguities, questions, and risk reads. A recitation of
   this brief is NOT a gate.
4. **WAIT for User-Operator confirmation.** Only then act. Any irreversible/external step
   (a post, a submission) is read back at that step too — only the single action the LA
   approved for this piece.

## Read list (≤6, first-action)

- `docs/research/publication-program/README.md` — program instruction + §0 standards
- `docs/research/publication-program/AUTHOR_KIT.md` — working rules; §B pass; §D privacy screen (your hardest section); §F disclosure (ACTIVE)
- `docs/research/publication-program/VERIFIED_FACTS.md` — fact sheet; NOTE the specimen-count row (7 enumerated; "~8" was an estimate — you re-count from the journal)
- `docs/research/publication-program/novelty-survey/P2-verdict.md` — your survey verdict: ancestor map, venue mechanics, the four sensitive specimens
- `docs/research/publication-program/ROADMAP.md` §5 — the LA's ceremony decisions
- Vikunja #959 (your ticket; epic #956) — live state + LA comments

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

Write the security-education long-form: a curated specimen collection of documented
composition failures — two individually-correct controls colliding — from one fully
instrumented system, each specimen presented as setup → collision → root cause →
SHIPPED structural fix → transferable rule. WHY: the artifact (not the idea) is the
unclaimed contribution, and it builds the LA's security-education standing that P4
later rides. Drafts end at LA ceremonies; nothing posts.

## Scope remaining + closure criteria

- **In:** deep novelty pass (§I, written GO/NO-GO) → enumerate the EXACT specimen set
  from the journal archives (fact sheet has 7 enumerated; the "~8" was an estimate —
  the count that prints is the count you derive) → harvest each specimen's journal
  entries verbatim + commits/tickets → outline → long-form draft for home base + the
  HN-shaped variant if the panel flags length → §B pass → panel → revise → LA ceremony.
- **Binding shape (survey):** cite the ancestors UP FRONT (Zave feature-interaction,
  Perrow, Cook, Shortridge/Rinehart) — lead with what's new (security controls, one
  instrumented system, shipped fixes), never with "composition failures exist." Title
  hazard: no gratuitous-number titles ("8 ways…") — HN guidelines crop them.
- **The four trust-spine specimens** (SSRF-precheck kill-switch, replay window,
  unreachable ALLOW, leak-validator swallow) print ONLY as closed-with-remedy, and get
  the tightest integrity/privacy screen; nothing about live egress/policy config
  beyond what the public mirror exposes. The two egress-adjacent ones get the hardest
  review. When unsure: exclude and flag (README §0.8).
- **Closure:** panel zero-reds + dispositions → LA ceremony → the specific approved
  action only. #959 closes when the LA declares P2 done or kills it.
- **Deferred/blocked:** none at brief time; anything deferred gets ticket
  CURRENT-STATE + queue entry with unblock predicate.

## Risks

- **Thesis-novelty overclaim (highest):** the phenomenon is 30+ years documented — the
  framing instruction above is binding, not stylistic.
- **Partial-vulnerability-disclosure reading:** a specimen written as "collision"
  without "fix shipped" reads as an open hole in a live system. Every specimen closes.
- **Survivorship/n=1:** these are collisions we CAUGHT on one system — scope claims
  accordingly; "structural fix" is ours-on-this-architecture, not a law.
- **Venue access gaps from the survey:** ACM Queue likely invite-only (aspirational);
  IEEE S&P = department pitch, mechanics page was JS-blocked — verify live if/when the
  LA green-lights pitches (post-first-pieces per Decision c).
- **Date/SHA drift:** every specimen date and commit re-derived (§B) — the specimen
  list in the verdict/fact sheet is a map, not the territory.

## Operational constraints (inherited)

CLAUDE.md binds: never-destructive-git · feature-branches-only · no `git add -A` ·
LOCALAPPDATA-redirect for pytest · journal fragment for the ship. Program layer:
README §0 (read-only research; per-piece LA approval; n=1; §B pass; §D screen).

## Authorizations (explicit + bounded)

After YOUR gate: research, harvest, outline, draft, panel, revise — autonomously. NO
posting/submitting/commenting/account actions anywhere, ever, without the LA's
per-piece approval of that single named action. Venue set FIXED per ROADMAP §5c;
Reddit NOT approved; talk CFPs (BSides 2027) are watch-list only until the LA says
otherwise.

## Memory / subagent / substrate pointers

Memories: `feedback_soften_certainty_in_public_posts` ·
`feedback_scrub_pollution_dont_caveat` (a cut specimen is CUT — no "we removed X"
residue) · `feedback_verify_commit_sha_against_file_history`. SSOT: the program files
in the read list; review panel spec README §4. Pacing: Decision d = two threads; P2 is
an essay-thread candidate alongside P3 — check the epic for which slot is open.

## Reference SHAs + anchors (cold-start verification)

Phase 0 foundation bd06c6e6 · survey pack 05f40842 (land on main via the Phase-0 merge).

```anchors
# type   | value      | label                                  | derivation (count rows only)
sha      | af296b77   | predecessor_session_anchor (Phase-0 fork point)
path     | docs/research/publication-program/README.md | canonical program instruction
path     | docs/research/publication-program/AUTHOR_KIT.md | working rules + rubric + active disclosure
path     | docs/research/publication-program/VERIFIED_FACTS.md | checked fact sheet (specimen-count row)
path     | docs/research/publication-program/novelty-survey/P2-verdict.md | this piece's survey verdict
count    | 7          | novelty-survey verdicts committed      | ls docs/research/publication-program/novelty-survey/*.md 2>/dev/null | wc -l
ticket   | #959       | this piece's ticket
ticket   | #956       | program epic
```

## Predecessor state at author time

Phase 0 complete; LA ceremony 2026-07-19: disclosure=full-transparency (§F ACTIVE),
home base=GitHub Pages-for-now (domain possible in weeks — migration-friendly
permalinks), venues per ROADMAP §5c, pacing=2 threads, P1–P6 keep / P7 park. Nothing
posted anywhere. App DOWN at handoff. Main HEAD at brief authoring: af296b77 (pre-merge).
