---
artifact_type: handoff-brief
target_session: fresh Claude Code session, this repo (P1 author session)
predecessor_session_anchor: af296b77
status: HANDOFF
date: 2026-07-19
---

# Author brief — P1: The Lunar Lake performance corpus (series S1–S4)

Committed program artifact (LA amendment 2, 2026-07-19): lives in
`docs/research/publication-program/author-briefs/`, not gitignored handoffs.

## SUCCESSOR: START HERE

Do NOT edit / build-that-mutates-state / post / git-write until step 4 completes.

1. **Read** the ≤6 first-action reads below — ground on live disk/Vikunja, not this brief's summary.
2. **Verify anchors (machine-checked, not by eye)**: run
   `python scripts/verify_handoff_brief.py docs/research/publication-program/author-briefs/P1-author-brief.md`.
   Non-zero exit ⇒ the brief is stale ⇒ surface it, do not proceed.
3. **Comprehension gate** to the User-Operator: the FULL `CLAUDE.md` `<comprehension_gate>`
   section list, in your OWN words — substantive and substrate-grounded, sized to the work,
   surfacing your own assumptions, ambiguities, questions, and risk reads. A recitation of
   this brief is NOT a gate.
4. **WAIT for User-Operator confirmation.** Only then act. For any irreversible/external
   step (a post, a submission), read the content back at that step too — and it must be
   the single, specific action the LA approved for this piece.

## Read list (≤6, first-action)

- `docs/research/publication-program/README.md` — canonical program instruction + §0 standards
- `docs/research/publication-program/AUTHOR_KIT.md` — working rules; §B date/number pass; §F disclosure (ACTIVE: full transparency); §I rubric for your deep novelty pass
- `docs/research/publication-program/VERIFIED_FACTS.md` — the checked fact sheet; re-verify every VOLATILE row you rely on
- `docs/research/publication-program/novelty-survey/P1-verdict.md` — your survey verdict: prior-art map, series carve, venue mechanics, risks
- `docs/research/publication-program/ROADMAP.md` §5 — the LA's five ceremony decisions (venue list, pacing, disclosure)
- Vikunja #958 (your ticket; epic #956) — live state + any LA comments since this brief

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

Produce the program's opening publications: a four-post performance series that makes
this project the reference field corpus for a heterogeneous local-AI stack on Lunar
Lake silicon, and earns the LA's OpenVINO community standing. WHY: the credibility
ladder — checkable data publishes first so every later essay has a verifiable record
to stand on. Nothing in this mission includes posting; drafts end at LA ceremonies.

## Scope remaining + closure criteria

- **In:** deep novelty re-verification (your own §I pass — a written GO/NO-GO you must
  justify; NO-GO is respectable) → source harvest (PERFORMANCE_LOG dated entries +
  `docs/performance/*.json` + anthology entries verbatim) → outline → draft S4 first
  (the #725→PR #4082 upstream-fix story; the credibility handshake), then S1
  (co-residency — the white-space flagship). S2 (honest spec-decode ledger — MUST cite
  and reconcile the LA's own OpenVINO Discussion #36484; different experiment than the
  16K figures, say so) and S3 (NPU embedding offload honestly) as material readies.
  KV-cache/MoE material distributes into S1/S2 or becomes an optional methods post.
- **Binding shape (survey + ceremony):** a SERIES, never one benchmark dump; NEVER lead
  with raw tok/s (saturated — position against Intel/arXiv/TechHara by name); every
  post carries a community-grade methods section + what-was-NOT-measured (LA amendment
  4); prior-work treatment from the verdict's map, deepened.
- **Coordination:** `docs/performance/community_export/` staging is another session's
  in-flight work — read its ticket state at author time; coordinate, do not touch.
- **Closure:** per post — review panel (README §4) zero unresolved reds → LA ceremony
  (final draft + one-page claims memo) → LA approves/requests/kills. The ticket (#958)
  closes when the LA declares the series complete or kills the remainder.
- **Deferred/blocked:** none at brief time. Anything you defer gets BOTH halves: ticket
  CURRENT-STATE comment AND a queue entry with an unblock predicate.

## Risks

- **Superseded figures (deadliest here):** PERFORMANCE_LOG entries supersede each other
  (the 05-22 spec-decode figure; the same-evening cross-runtime addendum A1). Cite the
  LATEST + both sides of the 1.8×/1.2× pair. AUTHOR_KIT §B trap 3.
- **Self-duplication:** Discussion #36484 already publishes spec-decode numbers under
  the LA's handle — S2 must build on it, not restate or contradict it.
- **Upstream-state drift:** PR #4082 merged 2026-07-08 (API-verified); release
  inclusion UNVERIFIED — never write "shipped in release X" without checking tags that
  day. §B trap 2.
- **Vendor-relations tone:** NPU-honesty and llama.cpp comparisons stay collaborative
  ("on this box, these versions"), never a verdict on Intel or llama.cpp.
- **Privacy screen:** no local usernames/hostnames/absolute paths/live policy config;
  public-mirror paths only in print (AUTHOR_KIT §D).
- **HF PRO gate:** personal-namespace Hugging Face blogging appears to need the paid
  PRO tier — surface to the LA at the moment it is actually needed; account/payment
  actions are his, never yours.

## Operational constraints (inherited)

CLAUDE.md binds: never-destructive-git · feature-branches-only · no `git add -A` ·
LOCALAPPDATA-redirect for any pytest · journal fragment for the substantive ship ·
performance results recorded when run. Program layer: README §0 (read-only research;
per-piece LA approval; n=1 framing; §B date/number pass before the panel sees a draft).

## Authorizations (explicit + bounded)

After YOUR gate passes: research, harvest, outline, draft, self-check, convene the
review panel, revise — autonomously. You may NOT: post/submit/comment anywhere, create
accounts, or take any publishing action. The LA ceremony approves ONE named action per
approval. Venue set is FIXED per ROADMAP §5c (home base · HN · LessWrong · OpenVINO
DevRel coordination · Hugging Face); Reddit is NOT approved. Multi-session work hands
off via a template-compliant brief.

## Memory / subagent / substrate pointers

Memories: `feedback_engagement_first_upstream_contribution` ·
`feedback_share_info_promptly_in_community_dev` ·
`feedback_github_comments_use_api_not_webfetch` ·
`feedback_soften_certainty_in_public_posts` · `feedback_collaborative_upstream_outreach`.
SSOT docs: the four program files in the read list. Review panel spec: README §4.
Pacing: Decision d = two threads in flight; P1 is the data thread and goes first.

## Reference SHAs + anchors (cold-start verification)

Phase 0 foundation bd06c6e6 · survey pack 05f40842 (both land on main via the Phase-0
merge; this brief ships inside it).

```anchors
# type   | value      | label                                  | derivation (count rows only)
sha      | af296b77   | predecessor_session_anchor (Phase-0 fork point)
path     | docs/research/publication-program/README.md | canonical program instruction
path     | docs/research/publication-program/AUTHOR_KIT.md | working rules + rubric + active disclosure
path     | docs/research/publication-program/VERIFIED_FACTS.md | checked fact sheet
path     | docs/research/publication-program/novelty-survey/P1-verdict.md | this piece's survey verdict
count    | 7          | novelty-survey verdicts committed      | ls docs/research/publication-program/novelty-survey/*.md 2>/dev/null | wc -l
ticket   | #958       | this piece's ticket
ticket   | #956       | program epic
```

## Predecessor state at author time

Phase 0 (Editorial Board) complete: gate passed with 7 LA amendments; seven surveys
run read-only; LA ceremony 2026-07-19 decided disclosure=full-transparency, home
base=GitHub Pages-for-now (standalone domain possible in weeks — keep permalinks
migration-friendly), venue list per ROADMAP §5c, pacing=2 threads, P1–P6 keep / P7
park. Nothing has been posted anywhere. App state at handoff: DOWN. Main HEAD at brief
authoring: af296b77 (pre-merge).
