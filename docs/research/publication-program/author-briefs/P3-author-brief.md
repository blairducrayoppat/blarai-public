---
artifact_type: handoff-brief
target_session: fresh Claude Code session, this repo (P3 author session)
predecessor_session_anchor: af296b77
status: HANDOFF
date: 2026-07-19
---

# Author brief — P3: The instrument-trust ladder (merged essay)

Committed program artifact (LA amendment 2, 2026-07-19).

## SUCCESSOR: START HERE

Do NOT edit / build-that-mutates-state / post / git-write until step 4 completes.

1. **Read** the ≤6 first-action reads below — ground on live disk/Vikunja, not this brief's summary.
2. **Verify anchors (machine-checked, not by eye)**: run
   `python scripts/verify_handoff_brief.py docs/research/publication-program/author-briefs/P3-author-brief.md`.
   Non-zero exit ⇒ stale brief ⇒ surface it, do not proceed.
3. **Comprehension gate** to the User-Operator: the FULL `CLAUDE.md` `<comprehension_gate>`
   section list, in your OWN words — substantive and substrate-grounded, sized to the work,
   surfacing your own assumptions, ambiguities, questions, and risk reads. A recitation of
   this brief is NOT a gate.
4. **WAIT for User-Operator confirmation.** Only then act. Irreversible/external steps
   are read back at that step — only the single LA-approved action.

## Read list (≤6, first-action)

- `docs/research/publication-program/README.md` — program instruction + §0 standards
- `docs/research/publication-program/AUTHOR_KIT.md` — working rules; §B pass; §I rubric (you re-run it DEEPER at draft start — mandatory here, see Mission); §F disclosure (ACTIVE)
- `docs/research/publication-program/VERIFIED_FACTS.md` — fact sheet
- `docs/research/publication-program/novelty-survey/P3-verdict.md` — your verdict: the prior-art map per rung, the merge caveats, venue mechanics
- `docs/research/publication-program/ROADMAP.md` §5 — the LA's ceremony decisions
- Vikunja #960 (your ticket; epic #956) — live state + LA comments

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

Write ONE essay (the merge is confirmed) unifying the instrument-trust ladder — tests
→ live-verify → instruments that must EARN belief via positive controls — with the
honesty machinery (four-grade scale, FALSE-DONE zero tolerance, verdict grammars,
deterministic gate under every soft oracle) as its mechanism half. Positioned as
cross-domain SYNTHESIS crediting prior art in the first breath; the unclaimed ground
is the unification + the meta-trust rung + our named incidents. WHY: the epistemology
piece that makes P5's flagship claims legible. Drafts end at LA ceremonies.

## Scope remaining + closure criteria

- **MANDATORY FIRST SUBSTANTIVE STEP:** a fresh novelty re-survey. Three of the closest
  competitors were UNDER A WEEK OLD at survey time (Proof-or-Stop arXiv 2607.14890,
  2026-07-16; TestDino, 2026-07-14; False Success arXiv 2606.09863). The 2026-07-19 GO
  expires with the field — your GO/NO-GO must re-justify against whatever exists at
  draft time. NO-GO is respectable and costs the program nothing.
- **In:** the re-survey → harvest named incidents verbatim (file:// screenshots
  convicting an innocent app; the grader with the answer key in its pocket; the
  three-instrument perf scare; rigged-reds) → outline → draft (argument-first for the
  LessWrong register; the case as evidence) → §B pass → panel → revise → LA ceremony.
- **Binding shape (survey):** honesty machinery gets its OWN related-work paragraph
  (its map — Proof-or-Stop, False Success, TestDino — is distinct from the ladder's:
  DeMillo/mutation, Barr oracle survey, chaos engineering, EvalGen, Panickssery);
  extraction-to-a-short stays an option if it dilutes the essay.
- **Closure:** panel zero-reds + dispositions → LA ceremony → only the approved
  action. #960 closes when the LA declares P3 done or kills it.
- **Deferred/blocked:** none at brief time.

## Risks

- **Overclaim (make-or-break):** presenting the ladder/positive-controls/false-done as
  NOVEL is falsified in one citation — position as synthesis, credit up front.
- **Field velocity:** the honesty-machinery half is the exposed flank; re-survey it
  hardest.
- **LessWrong mechanics:** first post human-reviewed; sub-5-karma rate limits;
  frontpage moderator-decided — write argument-first or it lands as Personal-blog.
- **HN hazards:** normal link only; NO vote solicitation (a real hazard for a
  fleet-built piece — never ask anyone to upvote); no editorialized title.
- **Incident specificity vs the leak screen:** the incidents are internal — every
  detail passes §D; public-mirror paths only.

## Operational constraints (inherited)

CLAUDE.md binds: never-destructive-git · feature-branches-only · no `git add -A` ·
LOCALAPPDATA-redirect for pytest · journal fragment for the ship. Program layer:
README §0; AUTHOR_KIT §§A–J.

## Authorizations (explicit + bounded)

After YOUR gate: re-survey, harvest, outline, draft, panel, revise — autonomously. NO
posting/submitting/commenting/account actions without the LA's per-piece approval of
that single named action. Venue set FIXED per ROADMAP §5c (home base · LessWrong ·
HN); Reddit NOT approved.

## Memory / subagent / substrate pointers

Memories: `feedback_soften_certainty_in_public_posts` ·
`feedback_adversarial_review_author_verifier_separation` (the panel never rewrites).
SSOT: program files in the read list; panel spec README §4. Pacing: Decision d = two
threads; P3 is an essay-thread candidate alongside P2 — check the epic for the open slot.

## Reference SHAs + anchors (cold-start verification)

Phase 0 foundation bd06c6e6 · survey pack 05f40842 (land on main via the Phase-0 merge).

```anchors
# type   | value      | label                                  | derivation (count rows only)
sha      | af296b77   | predecessor_session_anchor (Phase-0 fork point)
path     | docs/research/publication-program/README.md | canonical program instruction
path     | docs/research/publication-program/AUTHOR_KIT.md | working rules + rubric + active disclosure
path     | docs/research/publication-program/VERIFIED_FACTS.md | checked fact sheet
path     | docs/research/publication-program/novelty-survey/P3-verdict.md | this piece's survey verdict
count    | 7          | novelty-survey verdicts committed      | ls docs/research/publication-program/novelty-survey/*.md 2>/dev/null | wc -l
ticket   | #960       | this piece's ticket
ticket   | #956       | program epic
```

## Predecessor state at author time

Phase 0 complete; LA ceremony 2026-07-19: disclosure=full-transparency (§F ACTIVE),
home base=GitHub Pages-for-now (domain possible in weeks — migration-friendly
permalinks), venues per ROADMAP §5c, pacing=2 threads, P1–P6 keep / P7 park. The P7
park matters to you: if the honesty-machinery half is later extracted as a short, that
is a NEW editorial decision for the LA, not a P7 revival by the back door. Nothing
posted anywhere. App DOWN at handoff. Main HEAD at brief authoring: af296b77 (pre-merge).
