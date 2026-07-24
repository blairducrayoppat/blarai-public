---
artifact_type: handoff-brief
target_session: fresh Claude Code session, this repo (P4 author session)
predecessor_session_anchor: af296b77
status: HANDOFF
date: 2026-07-19
---

# Author brief — P4: Structural absence beats vigilance

Committed program artifact (LA amendment 2, 2026-07-19).

## SUCCESSOR: START HERE

Do NOT edit / build-that-mutates-state / post / git-write until step 4 completes.

1. **Read** the ≤6 first-action reads below — ground on live disk/Vikunja, not this brief's summary.
2. **Verify anchors (machine-checked, not by eye)**: run
   `python scripts/verify_handoff_brief.py docs/research/publication-program/author-briefs/P4-author-brief.md`.
   Non-zero exit ⇒ stale brief ⇒ surface it, do not proceed.
3. **Comprehension gate** to the User-Operator: the FULL `CLAUDE.md` `<comprehension_gate>`
   section list, in your OWN words — substantive and substrate-grounded, sized to the work,
   surfacing your own assumptions, ambiguities, questions, and risk reads. A recitation of
   this brief is NOT a gate.
4. **WAIT for User-Operator confirmation.** Only then act. Irreversible/external steps
   are read back at that step — only the single LA-approved action.

## Read list (≤6, first-action)

- `docs/research/publication-program/README.md` — program instruction + §0 standards
- `docs/research/publication-program/AUTHOR_KIT.md` — working rules; §B pass; §F disclosure (ACTIVE)
- `docs/research/publication-program/VERIFIED_FACTS.md` — **the OpenClaw-conflation row is your load-bearing constraint** — read it before anything else in the sheet
- `docs/research/publication-program/novelty-survey/P4-verdict.md` — your verdict incl. §0 foil verification + the rebuilt-foil spec
- `docs/research/publication-program/ROADMAP.md` §5 — the LA's ceremony decisions
- Vikunja #961 (your ticket; epic #956) — live state + LA comments

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

Write the security-architecture piece arguing the unclaimed design stance: for agent
self-modification, the strongest control is a write path that structurally does not
exist — authorship relocated to an out-of-band human — versus the whole field's
strengthen-the-write-gate program. Backed by our shipped, dated first-party decision
(self-governance boundary, LA 2026-07-11) and a correctly-cited OpenClaw foil. WHY:
the most externally timely piece; AIGP-portfolio security-architecture evidence.
Drafts end at LA ceremonies.

## Scope remaining + closure criteria

- **In:** deep novelty pass (§I; the stance was unclaimed on 2026-07-19 — re-verify,
  the field moves) → re-verify the OpenClaw landscape (CVEs move; your verdict's §0 is
  a snapshot) → harvest the self-governance-boundary decision record + journal entries
  verbatim → outline → draft → §B pass → panel → revise → LA ceremony.
- **Binding foil spec (non-negotiable, from VERIFIED_FACTS + verdict §0):** the phrase
  "OpenClaw CVSS-8.8 memory chain" MUST NOT print — it is a verified three-way
  conflation. Foil = OpenClaw's self-written SOUL.md/MEMORY.md *design* ("gives the
  model a pen"); severity anchor = OWASP ASI06:2026 memory-poisoning class; incidents
  cited as what they are (ClawHavoc = supply-chain campaign; CVE-2026-25253 =
  WebSocket RCE; the actual memory CVE ≈ 6.0). Credit Koi Security; analytical
  register; zero vendor-bashing.
- **Binding argument spec:** pre-empt "this is just least privilege" with the three
  differentiators (least-privilege-against-the-grain when the field grants write;
  capability relocated to a human, not withheld; a direct rebuttal to the
  strengthen-the-write-gate program, e.g. the Mnemonic Sovereignty survey's own open
  problem). Do NOT cite the "Co-memorize diff-and-approve" pattern — the survey could
  not confirm it exists in that survey (likely misattribution).
- **Closure:** panel zero-reds + dispositions → LA ceremony → only the approved
  action. #961 closes when the LA declares P4 done or kills it. IAPP governance
  variant: post-first-pieces, LA-authored path (Decision a/c).
- **Deferred/blocked:** none at brief time.

## Risks

- **The foil (the whole credibility bet):** HN commenters WILL pull the CVE records —
  one wrong severity number ends the piece and dents the byline. Re-derive every
  external citation on draft day; archive-snapshot load-bearing pages.
- **"Someone already named this":** if your re-survey finds a prominent voice has
  since claimed the stance, that is a RESHAPE/NO-GO finding — report it, don't write
  around it.
- **Leak screen:** the piece describes our own security architecture — only what the
  public mirror exposes; the advisory-only learning loop is describable, its live
  config is not.
- **n=1:** ours is a documented single-system design decision, not a proven general
  superiority claim — INTERPRETATION-typed where it generalizes.

## Operational constraints (inherited)

CLAUDE.md binds: never-destructive-git · feature-branches-only · no `git add -A` ·
LOCALAPPDATA-redirect for pytest · journal fragment for the ship. Program layer:
README §0; AUTHOR_KIT §§A–J.

## Authorizations (explicit + bounded)

After YOUR gate: research, harvest, outline, draft, panel, revise — autonomously. NO
posting/submitting/commenting/account actions without the LA's per-piece approval of
that single named action. Venue set FIXED per ROADMAP §5c (home base · HN ·
LessWrong; IAPP later via the LA-authored path); Reddit NOT approved.

## Memory / subagent / substrate pointers

Memories: `project_blarai_self_governance_boundary` (the first-party decision this
piece is built on) · `feedback_soften_certainty_in_public_posts` ·
`feedback_collaborative_upstream_outreach`. SSOT: program files in the read list;
panel spec README §4. Pacing: Decision d = two threads; P4 enters when an essay slot
opens AFTER P2 (sequencing: it rides P2's security credibility).

## Reference SHAs + anchors (cold-start verification)

Phase 0 foundation bd06c6e6 · survey pack 05f40842 (land on main via the Phase-0 merge).

```anchors
# type   | value      | label                                  | derivation (count rows only)
sha      | af296b77   | predecessor_session_anchor (Phase-0 fork point)
path     | docs/research/publication-program/README.md | canonical program instruction
path     | docs/research/publication-program/AUTHOR_KIT.md | working rules + rubric + active disclosure
path     | docs/research/publication-program/VERIFIED_FACTS.md | checked fact sheet (OpenClaw-conflation row)
path     | docs/research/publication-program/novelty-survey/P4-verdict.md | this piece's survey verdict + foil spec
count    | 7          | novelty-survey verdicts committed      | ls docs/research/publication-program/novelty-survey/*.md 2>/dev/null | wc -l
ticket   | #961       | this piece's ticket
ticket   | #956       | program epic
```

## Predecessor state at author time

Phase 0 complete; LA ceremony 2026-07-19: disclosure=full-transparency (§F ACTIVE),
home base=GitHub Pages-for-now (domain possible in weeks — migration-friendly
permalinks), venues per ROADMAP §5c, pacing=2 threads, P1–P6 keep / P7 park. Nothing
posted anywhere. App DOWN at handoff. Main HEAD at brief authoring: af296b77 (pre-merge).
