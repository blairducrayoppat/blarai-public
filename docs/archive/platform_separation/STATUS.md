# Platform Separation — STATUS

**Living state file.** Update at the end of every stage. This is the single persistent artifact that travels between fresh VS Code Copilot sessions.

---

## v2 Banner (2026-04-24)

This plan is now at **v2** per [INFRA_DELTA_v2.md](INFRA_DELTA_v2.md). v1 baseline preserved at git tag `24ec0d9`.

v2 planning + GUIDE refactor are now merged to `main` (HEAD: `920c539`, ancestor of v2 branch parent `fce9ff4`). The `docs/platform-separation-v2` working branch was fast-forwarded into main and deleted on 2026-04-24 — do not look for it. All planning artifacts (stage XMLs, STATUS, GUIDE_PROMPT.xml, GUIDE_USAGE.md, audit/review docs) live on `main` now.

**Pre-execution invariant (historical)**: prior to Stage 0.9 the active branch was `main`. Stage 0.9 created `chore/platform-extraction` (HEAD captured in the Stage 0 ledger row), and from Stage 0 close onward the `Active branch (BlarAI)` row below reflects the actual checkout.

Major v2 deltas applied across all stage files (additive `<v2_updates>` blocks):
- **Fleet pause/resume triplet** wraps every destructive stage (Stage 0.0 + 4.0.6 + 4.13.5).
- **Worktree precondition** (`git worktree list` empty) checked at Stage 0.5.5 and re-verified at 4.0.5.
- **Vikunja Fleet Reports project_id locked at 8** (registry seed in 1.4.v2; spoofing guard in 2.7.v2).
- **All 14 Vikunja label IDs** (1=Active … 14=Gate:Escalation) seeded in `devplatform/projects/registry.yaml` at Stage 1.4.v2. (Label IDs are unrelated to scheduled-task count.)
- **Scheduled task count: 13** (verified 2026-04-25: `Get-ScheduledTask -TaskPath '\BlarAI\'` → 13 tasks, including `Escalation Watchdog`). v2 INFRA_DELTA originally claimed `escalation-watchdog` was a NEW task taking the count from ~13 → 14; this was incorrect — Escalation Watchdog already existed in the live 13. Asserted at 4.8.v2 and 6.7.v2 with the corrected count.
- **state.json schema_version=1** is tracked, NOT gitignored. `.lock` and `.tmp` siblings ARE ignored (1.3.v2).
- **wake_launcher.ps1** gains explicit `-BlarAIRoot` parameter (2.5.v2). Wake-template path scan at 4.7.5/4.7.6.
- **Doctrine splits (6.1/6.2/6.3) are DEFERRED** — Lead Architect already did SOP work on CLAUDE.md and copilot-instructions.md.
- **Test baseline**: ~981 passed, 22 skipped (was 755) per CLAUDE.md §Active State.

Function name reminder: `state.resume_fleet()` — NEVER `unpause_fleet()` (raises AttributeError).

---

## Current State

| Field | Value |
|---|---|
| Active branch (BlarAI) | `main` @ `4122b92` (Stage 5 merge commit; Stage 5 commit `3e73484` on chore/platform-extraction merged via `--no-ff`; chore/platform-extraction PRESERVED post-merge per copilot-instructions preservation rule) |
| Active branch (devplatform) | `main` @ Stage-5-close-unpause commit (mid-execution chain: `1a552d9` pause + `c20e298` Phase E + `ae75507` Phase F + close-unpause LAST action) |
| Last completed stage | **Stage 5 — Cleanup** (operationally CLOSED 2026-04-30; F.2 30-min mini-soak verified post-Phase-E + Phase-F; ack9 Class A LOAD-BEARING DISCHARGED at Item 5.5.v2 selective 4-of-17 governance delete preserving 13 BlarAI-internal architectural docs per A14) |
| Next stage to execute | **Stage 6 — Hardening** (LOW risk per Master Plan §6; Stage 6.7.5 hardening backlog 28 tickets; could optionally go through fleet now per Master Plan §4) |
| Fleet scheduled tasks | Unpaused at Stage 5 close (LAST action per fleet-pause SOP §3); 5 tasks remain DISABLED per LA Phase A directive (Welcome Back Poll, Daily Digest, Weekly Summary, Dashboard Maintainer, Toast Watchdog), 8 ACTIVE (Wake SDO, Wake Co-Lead Architect, Wake EA Code, Sprint Auditor, Agents Cadence Monitor, Credentials Rotation Reminder, Escalation Watchdog, Gate Stale Cleaner) |
| Vikunja server | Running on host (Stage 4 cutover complete; devplatform DB authoritative at `%LOCALAPPDATA%\Vikunja\vikunja.db` per LA n1(c)) |
| MCP configs | All point to devplatform (Item 4.6 cutover, 2026-04-28) |

---

## Stage Ledger

| Stage | Status | Date | BlarAI commit | devplatform commit | Key evidence |
|---|---|---|---|---|---|
| 0 Preflight | COMPLETE | 2026-04-24 | `chore/platform-extraction` @ d0dc1c7 (pre-STATUS-commit) | — | Tag `pre-platform-extract` (object `ce2ec58`) on `d0dc1c7`; bundle SHA256 `C051CCFB…D7707` (446,552,451 B); OOG zip SHA256 `15B4B9A1…29A8` (60,366,033 B); 13 scheduled-task XMLs exported; 13/13 fleet tasks Disabled; manifest written; Vikunja Fleet Reports `project_id=8`; `state.json schema_version=1` confirmed; `VIKUNJA_PASS` persisted to User env (length 23); baseline JSON at `phase2_gates/evidence/platform_separation_stage0_baseline.json` |
| 1 Scaffold | COMPLETE | 2026-04-24 | _(this commit, on `chore/platform-extraction`; recover via `git log --oneline -1`)_ | `eaa005f` | devplatform repo on `main` with skeleton (tools/, docs/{adrs,runbooks}/, projects/, .vscode/, .github/, scripts/); `.gitignore` (v1 + v2.1.3 lock/tmp); `projects/registry.yaml` with all 14 label IDs seeded + projects.blarai=3, devplatform_meta=10, fleet_reports=8; `.venv` (Python 3.11.9); `pyproject.toml` (name=devplatform, requires-python>=3.11); placeholder CLAUDE.md / AGENTS.md / .github/copilot-instructions.md / README.md (with Worktrees-scope §); BlarAI `.platform/vikunja_project_ids.yaml` reverse lookup; Vikunja stopped post-1.4(e) restoring Stage-0.4 invariant |
| 2 Refactor (multi-project seam) | COMPLETE | 2026-04-26 | `chore/platform-extraction` @ `3d1ac35` (single Stage-2 commit folding Items 2.1–2.9; 69 files / +12955 −74) | — | `_vikunja_client.py` + `_project_context.py` chokepoint helpers; per-project allowlist `tools/autonomy_budget/projects/blarai.yaml`; `--project-root` / `--project-id` flags threaded through 13 Python entrypoints; `-BlarAIRoot` parameter + `BLARAI_ROOT` env-fallback in 6 PS1 helpers; `LiveVikunjaClient.update_task` new method + 6-caller D2 closure (g5-4 SATISFIED); MCP server handlers DIVERGE per D4 (7 `_require_project_id` retained); 4 V matrix tests authored at 2.7.v2 (V4=12 cases CLI-flag, V5=1 case `-BlarAIRoot` PS1, V6=50 cases MCP project_id, V7=6 cases cross-project byte-identity); pytest tools/ baseline 282 → **351 passed** (net +69); pyproject.toml in diff (i1-3 satisfied); see Stage 2 Closure Footnotes §1–12 below |
| 3 Copy tools | COMPLETE | 2026-04-28 | _(this STATUS append commit on `chore/platform-extraction`; recover via `git log --oneline -1`)_ | `main` @ `95884a0` (single Stage-3 commit; 189 files / +39592 −2 / parent `3894221`) | devplatform/tools/ populated (autonomy_budget, fleet_observability, fleet_ops, gate_stale_cleaner, scheduled-tasks, vikunja_mcp, vikunja, _project_context.py, _vikunja_client.py); docs/ populated (governance fleet-only subset 4 of 17, runbooks 12+1 relocated F3, scheduled wake_templates 6, Claude/CO_LEAD/Domain governance pack per Stage 3.3 expansion); .mcp.json + .vscode/{mcp.json,tasks.json} (per-file top-level keys preserved: `mcpServers` vs `servers`); pyproject.toml authored from empirical import-graph derivation (httpx, pyyaml, mcp, jsonschema; pytest+pytest-asyncio extras); tools/tests/ promoted Class D → Class C (n13(f) F-N11); .gitignore augment (n13(e): `tools/scheduled-tasks/logs/`, `tools/fleet_observability/escalation_seen.json{,.tmp}`, `devplatform.egg-info/`); `.copy_manifest_v2.yaml` (n13(g): 10 v1 + 21 v2 entries, 195 v2_files); pip install + import verify + `pytest --collect-only` (351 tests, 0 errors); daily_digest --help non-destructive smoke (n13(d): exit 0); forward+inverse drift verification (n13(h): no BlarAI substring; selective-copy scopes confirmed); pre-stage state.json sha256 `71FC1A2F…D5D19` UNCHANGED across commit; see Stage 3 Closure Footnotes below for anomalies + ack chain g7-ea1_n11/n12/n13 |
| 4 Cutover | COMPLETE | 2026-04-29 (Phase C remediation closed; soak verified 9:15→11:00 EDT) | _(this Stage-4-closure-record commit on `chore/platform-extraction` from `5965f6b`)_ | `df3d940` Stage 4 cutover + `48df457` doc-drift sweep + `b9b213d` post-stage unpause + `be22a15` Phase C wake_launcher remediation + `751c3df` handoff-prep pause | Vikunja DB migrated to devplatform; MCP configs cutover to devplatform; 13/13 tasks re-enabled at original Stage 4 close (Item 4.8); Phase A 2026-04-29 disabled 5 tasks per LA non-recognition (Welcome Back Poll / Daily Digest / Weekly Summary / Dashboard Maintainer / Toast Watchdog); Phase C 2026-04-29 remediated BUGs 1/2/4/5 (BUG 3 N/A given C3 architecture); 1h45m soak window 9:15→11:00 EDT verified 32 wake-* firings WORK-GATE skip + NO-WORK-EXIT, 24 cadence_monitor silent successes, 0 fail-open claude invocations; runtime/platform isolation confirmed mid-soak by LA test |
| 5 Cleanup | COMPLETE | 2026-04-30 | `chore/platform-extraction` @ `3e73484` (single Stage-5 commit; shortstat 335 files / +1120 / −33179; cumulative pre-merge diff 480 / +32942 / −37655 across 42 commits — see §8 for disambiguation) → merge `4122b92` on `main` (`--no-ff`); BlarAI tag `post-platform-extract` (object `67d0025`) on `4122b92` | `main` Stage-5-mid-execution: `1a552d9` (pause) + `c20e298` (Phase E remediation) + `ae75507` (Phase F remediation); devplatform tag `platform-extracted` (object `896d591`) on `ae75507`; close-unpause commit on devplatform main (LAST action per fleet-pause SOP §3) | 9 platform tool dirs/files deleted from BlarAI/tools/ at Item 5.1 (vikunja, vikunja_mcp, fleet_ops, fleet_observability, autonomy_budget, gate_stale_cleaner, scheduled-tasks, _vikunja_client.py, _project_context.py); openvino_contrib_agent + tests + __pycache__ orphan PRESERVED per keep_in_blarai; LA paste-relay #1 + #2 needed for S4U Agents Cadence Monitor disable/enable + zombie BlarAI Vikunja PID 11964 stop (per A23); 4 BlarAI coordination artifacts moved to `.platform/` at Item 5.3 per n1(m) atomicity rollback wrapper (sprints, scheduled, docs/active_tasks.yaml, docs/sprints); 34 platform-doctrine docs deleted from BlarAI/docs/ at Item 5.5; Item 5.5.v2 SELECTIVE 4-of-17 governance delete (STYLE, fleet-hygiene, merge-policy, parallel-sprints) PRESERVING 13 BlarAI-internal architectural docs per A14 + n1(e) Class A LOAD-BEARING; wake_templates wholesale-delete (6/6 fully migrated at Stage 3.2.v2); pyproject.toml testpaths reduced 15→9 at Item 5.6 per n1(g); .gitignore augmented at Item 5.7 (3 entries: `.claude/scheduled_tasks.lock` + `.platform/audit_archive/*.zip` + `.platform/audit_archive/pre_stage5_*/`); Item 5.8.v2 pytest baseline 1001 passed / 2 skipped / 0 failed (BENEFICIAL drift +20 vs CLAUDE.md 981/22; A30 bound; same 1003 collection total); Item 5.9 F.2 30-min mini-soak ALL ACCEPTANCE PASS (cadence_monitor + escalation_watchdog firings LTR=0; wake-* + sprint_auditor LTR=4 fleet_paused exit-4 per n3(j); 0 fail-open claude invocations verified via Get-CimInstance pwsh.exe parents; cadence_monitor_20260430.log Phase E n1(c) verified; 9 logs at devplatform path, 0 at BlarAI side); Item 5.0.5 audit archive `BlarAI/.platform/audit_archive/pre_stage5_20260430_013411.zip` 1499 files / 43 MB (n1(a) extension captured lifts.json + escalation_seen.json stragglers); Phase E mid-execution remediation per Item 5.4 audit (3 PS1 scripts cadence_monitor + escalation_watchdog + toast_watchdog Phase-C-BUG-1 pattern fix; commit c20e298) + Phase F mid-execution remediation per Item 5.4 broader-sweep (wake_launcher.ps1 7 dynamic-path edits beyond Phase C be22a15; commit ae75507; line 870 wake template gating Item 5.5.v2 unblocked); 132-atom cumulative-ack chain (g9-ea9_n1(a-n) Stage 5.0.v2 audit 14 sub-clauses + g9-ea9_n2(a-b) mid-execution); see Stage 5 Closure Footnotes below |
| 6 Hardening | IN-PROGRESS | 2026-05-08 | `a00cf95` (Phase 3 TicketA) + `7e0cc80` (Phase 3 STATUS.md/E11) + `dc9b205` (Phase 4 STATUS.md/E12) + _(this commit — Phase 6 STATUS.md/E14; recover via `git log -1 --oneline -- docs/platform_separation/STATUS.md`)_ | `1e21bc5` (Phase 2 pause) + `20d8fc2` (Phase 2 6.4) + `71436e7` (Phase 2 unpause) + `f50343a` (Phase 3 pause) + `dea5f3e` (Phase 3 TicketX) + Phase 3 unpause _(follows Phase 3 STATUS.md commit `7e0cc80`; recover via `git log --oneline main` on devplatform)_ + `049cc41` (Phase 4 pause) + `d478c05` (Phase 4 C1 on `feat/stage6-phase4-ps1-env-var-refactor`) + `36b86bd` (Phase 4 merge) + `57ce679` (Phase 4 unpause) + `681a905` (Phase 5 pause) + `bebd6e2` (Phase 5 C1 on `feat/stage6-phase5-cross-repo-path-fix`) + Phase 5 merge + Phase 5 unpause _(both follow Phase 5 STATUS.md commit E13; recover via `git log --oneline main` on devplatform)_ + `763a983` (Phase 6 pause) + `ea2fbf5` (Phase 6 C1 on `feat/stage6-phase6-ww-complete-task-fix`) + Phase 6 merge + Phase 6 unpause _(both follow this Phase 6 STATUS.md commit per dispatch ordering; recover via `git log --oneline main` on devplatform)_ | Items 6.4+6.5+TicketA+TicketX+TicketII+TicketJJ+TicketVV+TicketWW complete; 6.1-6.3/6.6 DEFERRED; 6.7-6.10 pending |

---

## Vikunja Project IDs

Populated during Stage 1.4. Leave empty until then.

| Project Name | Vikunja ID | Notes |
|---|---|---|
| BlarAI Core Development (canonical primary) | 3 | Resolved via REST `GET /api/v1/projects` 2026-04-24 (see Anomaly A4 — multiple BlarAI-related projects exist; #3 selected as canonical primary by name match) |
| DevPlatform-Meta | 10 | Created via REST `PUT /api/v1/projects` 2026-04-24 (see Anomaly A5 — created via REST not MCP because MCP Vikunja tools were not loaded in the Executor session) |
| Fleet Reports | 8 | Pre-seeded per Stage 1.4.v2 (carried from Stage 0.10.v2) |
| _(auxiliary BlarAI projects)_ | 4, 5, 6, 7, 9 | Recorded in `devplatform/projects/registry.yaml` under `blarai_auxiliary_projects` |

---

## Recovery Anchors

Populated during Stage 0.

| Artifact | Path | Created | Size (bytes) | SHA256 |
|---|---|---|---|---|
| Git tag | `pre-platform-extract` on commit `d0dc1c7` (object `ce2ec58`) | 2026-04-24 | N/A | N/A |
| Git tag | `post-platform-extract` on BlarAI commit `4122b92` (object `67d0025`) | 2026-04-30 | N/A | N/A |
| Git tag | `platform-extracted` on devplatform commit `ae75507` (object `896d591`) | 2026-04-30 | N/A | N/A |
| Git bundle | `C:\Users\mrbla\backups\BlarAI_pre_extract.bundle` | 2026-04-24 | 446,552,451 | `C051CCFB8FBC6CA31E03F48537816F56CC3FAFC927CEAFAEC9825C9EC65D7707` |
| OOG zip | `C:\Users\mrbla\backups\blarai_oog_20260424_171721.zip` | 2026-04-24 | 60,366,033 | `15B4B9A138974F500FFAE9682350F333DC228AC94A1DB184E26A220508A129A8` |
| Scheduled task XMLs | `C:\Users\mrbla\backups\scheduled_tasks_export\` (13 files) | 2026-04-24 | — | — |
| Manifest | `C:\Users\mrbla\backups\pre_extract_manifest.txt` | 2026-04-24 | — | (covers bundle + OOG zip) |
| Stage 0 baseline JSON | `phase2_gates/evidence/platform_separation_stage0_baseline.json` | 2026-04-24 | — | (committed on `chore/platform-extraction`) |

---

## Execution Log

Free-form log. Append a dated entry at the end of each stage session.

```
[YYYY-MM-DD HH:MM] Stage N started. Session model: <model>. Observations: ...
[YYYY-MM-DD HH:MM] Stage N complete. Commits: BlarAI <hash>, devplatform <hash>. Anomalies: ...
```

[2026-04-24 20:46Z] Stage 0 started. Session model: Claude Opus 4.7 (GitHub Copilot Chat). Observations: fleet was already paused pre-execution by Lead Architect; 7 worktrees drained by Lead Architect immediately prior; tree clean at pause commit `d0dc1c7`.
[2026-04-24 21:55Z] Stage 0 complete. Commits: BlarAI `chore/platform-extraction` @ d0dc1c7 (pause) + STATUS/baseline commit (this one). Anomalies: A1 (`mcpServers` key path — LOW), A2 (Vikunja CLI env injection at 0.10.v2 — LOW), A3 (`Agents Cadence Monitor` S4U elevation — HIGH, **CRITICAL for Stage 4.7**). Evidence: `phase2_gates/evidence/platform_separation_stage0_baseline.json`.
[2026-04-24 ~20:30Z] Stage 1 started. Session model: Claude Opus 4.7 (GitHub Copilot Chat). Comprehension gate: 2 iterations (iter 1 APPROVED_WITH_ADJUSTMENTS, iter 2 APPROVED). Observations: BlarAI tree clean on `chore/platform-extraction`; fleet still paused; 13/13 tasks Disabled.
[2026-04-24 Stage 1 close] Stage 1 complete. Commits: devplatform `eaa005f` (initial scaffold), BlarAI _(this STATUS commit on `chore/platform-extraction`)_. Vikunja project IDs resolved: BlarAI Core Development=3 (primary), DevPlatform-Meta=10 (created), Fleet Reports=8 (carried). Anomalies: A4 (multiple BlarAI Vikunja projects — LOW), A5 (REST API used in lieu of MCP tools — LOW).
[2026-04-24 Stage 1 close + 1] Between-stages cleanup pass (consolidated, Q7/Q8 included). Stage 1 EA, authorized by Lead Architect via Guide instance 2. Edits: _project_context.py generalization (Stage 2 XML 2.2), <vikunja_access_protocol> block (Stages 2, 3, 4), $BLARAI_PID regex (Stages 2.8, 3.7, 4.7), agent_gates_bus reclassification + architecture_decisions promotion + auxiliary-projects annotation (devplatform registry.yaml). Anomalies recorded: A6, A7, A8, A9, A10 (all LOW). Stage 1 closure status: UNCHANGED (still COMPLETE).
[2026-04-25 → 2026-04-26 Stage 2 multi-EA execution] Stage 2 substantive work executed across 5 EA cycles (EA-2 v1 → EA-3 v2/v3 → EA-4 v4 → EA-5 v5 → EA-6 closing) under 6 Guide-#6 disposition cycles in the Item 2.6+ phase. All Items 2.1–2.9 folded into a single mature commit at Stage 2 close per the v5 §work_remaining §2.9 commit_template.
[2026-04-26 Stage 2 close] Stage 2 complete. Commits: BlarAI `chore/platform-extraction` @ **`3d1ac35`** (single Stage-2 commit; 69 files / +12955 −74 / parent `f863a22`); devplatform unchanged (no Stage 2 devplatform-side work per stage XML scope). Test baseline pytest tools/: **351 passed** (pre 282; net add +69 from V matrix authoring at 2.7.v2: V4=12 + V5=1 + V6=50 + V7=6). Anomalies: A11 (alias-vs-rename — LOW) + 12-item Stage 2 Closure Footnotes (see new section above). Invariants preserved: fleet still paused (`state.json` `last_updated_by=copilot_agent`, `last_updated_utc=2026-04-24T20:46:12Z` verbatim across the full 2.5-day procedure cycle); 13/13 fleet tasks still Disabled; Vikunja still running on host per g6-ea6_n8 Option B (will be stopped at Stage 4.0/4.1 preflight); stash@{0} `sdo 20260424_013002` byte-identical 9-cycle preservation (v3 → v4 → Guide-5/6 → v5 → 2.7 → 2.7.v2 → docstring/2.8 → 2.9 → 2.10); no merge to main (gate at Stage 5.10 per R10); no governance edits (V8 / Stage 6.1.v2 deferred). g6-ea6_n9 STATUS-append component DISCHARGED at this entry. Stage 2 transitions to Stage 3 (separate fresh-EA spawn — NOT EA-6's responsibility per Guide-#6 proceed_authorization).
[2026-04-27 Stage 3 started] Stage 3 started. Session model: Claude Opus 4.7 (GitHub Copilot Chat). Comprehension gate iter-1 emitted per `3.0-EA_INITIALIZATION_INSTANCE_1_STAGE3_COPY_TOOLS.xml` `required_first_actions`. V0a–V0M pickup verification PASS. Three Guide-#7 arbitration cycles authored across the multi-day Stage 3 work: g7-ea1_n11 (selective tools/+docs/ scope) → g7-ea1_n12 (governance selective + Stage 3.3 expansion) → g7-ea1_n13 (8 sub-clauses (a)–(h) binding remaining Items 3.4..3.10.v2 amendments). Naming defect (EA-1 vs EA-7 ID drift) recorded as A12 with verbatim-restatement-per-no-amend disposition. BlarAI-side read-only invariant maintained throughout (sole exception: this Stage 3 close STATUS append).
[2026-04-28 Stage 3 close] Stage 3 complete. Commits: devplatform `main` @ **`95884a0`** (single Stage-3 commit; 189 files / +39592 −2 / parent `3894221`); BlarAI _(this STATUS append commit on `chore/platform-extraction`)_. 9-step execution_ordering completed in order: 3.4 → 3.4.5 → 3.5 → 3.6 → 3.7 → 3.8 → 3.10.v2 → 3.9 → 3.10. `pytest --collect-only` on devplatform-side post-copy: 351 tests, 0 errors. `daily_digest --help` non-destructive smoke: exit 0. Forward+inverse drift verification: PASS. Anomalies: A12 (Stage 3 EA identifier drift — LOW), A13 (F3_BASH_FORK_ERROR_RUNBOOK relocation — LOW), A14 (selective governance subset + Stage 3.3 expansion — LOW) + 6-item Stage 3 Closure Footnotes (see new section above). Invariants preserved: BlarAI source untouched (read-only); single Stage-3 commit on devplatform main parent 3894221; fleet still paused (`state.json` SHA256 `71FC1A2F…D5D19` UNCHANGED pre→post commit; `last_updated_by=copilot_agent`, reason `platform separation v2 in progress`); Vikunja still running on host per g6-ea6_n8 (will stop at Stage 4 preflight); `.copy_manifest_v2.yaml` (10 v1 + 21 v2 entries) co-committed; `devplatform.egg-info/` correctly excluded via gitignore + explicit-allow-list staging. Stop_condition status at close: (i)(ii)(iii)(iv) NOT triggered; (v) deferred to Stage 4 live-load smoke. Stage 3 transitions to Stage 4 (separate fresh-EA spawn). g7-ea1_n13 STATUS-append component DISCHARGED at this entry.
[2026-04-28 → 2026-04-29 Stage 4 multi-phase execution] Stage 4 (Cutover) executed by Guide-#8 (Claude Code Opus 4.7) supervising EA-8 (VS Code Copilot Opus 4.7). LA-6 hybrid gating cadence applied (per-item HOLD for high-risk; bundled for low-risk). Initial close 2026-04-28: devplatform cutover commits `df3d940` + `48df457` + `b9b213d`; BlarAI close marker `5965f6b`; 13/13 tasks re-enabled (Item 4.8 + n3(k) carve-out for 3 S4U/Enabled=false tasks); 115 binding atoms; A15 anomaly. Post-cutover 5-bug discovery + Phase A/B/C/D remediation 2026-04-29: LA risk-check question prevented ~$58 overnight cost bleed from BUG 5 fail-OPEN; Phase A disabled 5 unused scheduled tasks per LA directive; Phase C1 reverted `.mcp.json` template → literal (uncommitted, gitignored per Ticket I); Phase C3+C4 wake_launcher path resolution fix committed at devplatform `be22a15` (lines 69 + 809 → `$PSScriptRoot`-derivation); 820 BlarAI logs migrated to devplatform for historical preservation; Phase D 1h45m soak 9:15→11:00 EDT verified 32/32 wake-* WORK-GATE skip + 24/24 cadence_monitor silent successes + 0 fail-open claude invocations; runtime/platform isolation confirmed mid-soak by LA's BlarAI runtime launch + prompt response test. Anomalies bound: A16 (BUG 5 fail-OPEN; HIGH), A17 (STATUS.md duplication AMBIGUOUS), A18 (subagent verification false-negative), A19 (BUG 1 wake_launcher reads stale BlarAI state.json; MEDIUM). Stage 6.7.5 backlog: 19 tickets (II/JJ/KK new from Phase C; GG/HH from Stage 4 execution). Cumulative-ack chain: 116 binding atoms (n3(l) Item 4.13 STATUS.md surgical truncate added). Stage 4 declared operationally CLOSED at 2026-04-29.
[2026-04-29 Stage 4 close (this commit)] Stage 4 closure record commit on `chore/platform-extraction` from `5965f6b`. STATUS.md updated per Stage 3 closure pattern: Current State table refreshed, Stage Ledger Stage 4 row marked COMPLETE, Anomalies A15-A19 subsections appended, Stage 4 Closure Footnotes section authored (8 footnote items), Phase C addendum appended to Stage 4 COMPLETE marker. Guide-#8 → Guide-#9 handoff XML to follow at `GUIDE_HANDOFF_LATEST.xml`. Stage 4 transitions to Stage 5 — fresh Guide-#9 (Stage 5 planning) + fresh EA-9 (Stage 5 execution) spawn pattern per established Guide-#7 → Guide-#8 precedent (`b9a173d`). g8-ea8_n3(l) STATUS-append component DISCHARGED at this entry.

---

## Anomalies / Deviations from Plan

Record any deviation from the stage XML here. If a work item was skipped, modified, or encountered unexpected state, note it with:
- Stage + work item ID
- What was different
- What was done instead
- Why it's safe (or what risk it introduces)

### A1 — `mcpServers` key path (Stage 0, work item 0.0.5) — LOW

- **What was different**: XML command reads `$cfg.servers.vikunja.env.VIKUNJA_PASS`. Actual key in `.mcp.json` is `mcpServers` (capitalized, plural).
- **What was done**: Used `$cfg.mcpServers.vikunja.env.VIKUNJA_PASS`. Literal was read and persisted to User env (length 23).
- **Why safe**: Read-only access to the JSON config; no mutation of `.mcp.json`. Functional outcome identical to XML intent.
- **Follow-up**: Post-procedure review of stage XML 0.0.5 command block. Stage XMLs are locked during execution.

### A2 — Vikunja CLI env-injection deviation (Stage 0, work item 0.10.v2) — LOW

- **XML command**: `python tools/vikunja_mcp/cli.py list-projects | Select-String "Fleet Reports"`
- **Actual command run**: `$env:VIKUNJA_PASS = (Get-Content C:\Users\mrbla\BlarAI\.mcp.json -Raw | ConvertFrom-Json).mcpServers.vikunja.env.VIKUNJA_PASS; python tools/vikunja_mcp/cli.py list-projects | Select-String "Fleet Reports"`
- **Reason**: `tools/vikunja_mcp/cli.py` reads `VIKUNJA_PASS` from the process environment at startup. In the active shell (which had not been relaunched since 0.0.5 persisted the variable to User scope), the variable was not present in `$env:`, so the CLI would have failed authentication. A one-shot session-scoped injection from the same `.mcp.json` literal made the CLI invocation succeed without modifying any persisted state.
- **Why semantically equivalent**: The injected value is byte-identical to the literal that the MCP runtime would have supplied; the CLI behavior, output, and the captured evidence (`Fleet Reports` `project_id=8`) are identical to running it after a shell relaunch.
- **Follow-up**: None — the User-scoped env var will be picked up by future shells naturally; no XML change recommended.

### A4 — Multiple BlarAI-related Vikunja projects (Stage 1, work item 1.4 step c) — LOW

- **What was different**: Stage XML 1.4 step (c) and `registry.yaml`'s `projects.blarai.vikunja_project_id` schema imply a single BlarAI project. The Vikunja server actually has 6 BlarAI-related projects: `BlarAI Core Development` (id=3), `BlarAI Infrastructure` (id=4), `Architecture Decisions` (id=5), `BlarAI Agent Gates` (id=6), `BlarAI Fleet Dashboard` (id=7), `BlarAI Drafts` (id=9). Plus `Fleet Reports` (id=8) handled separately.
- **What was done**: Selected `BlarAI Core Development` (id=3) as canonical primary by name match (closest semantic fit to "BlarAI"). The other 5 IDs were recorded in `devplatform/projects/registry.yaml` under a new `blarai_auxiliary_projects:` map so future tooling can enumerate full BlarAI scope.
- **Why safe**: All current fleet tools query a single `project_id` at a time and pass it explicitly per Master Plan §D.1; nothing aggregates across projects today. Selection is documented and recorded for Stage 2 review.
- **Follow-up**: Stage 2 (refactor seam) should confirm whether any tool needs to address the auxiliary projects; if so, extend `blarai.yaml` schema with a `secondary_project_ids:` list and update `_project_context.py`.

### A5 — REST API used instead of MCP tools (Stage 1, work item 1.4 step c) — LOW

- **XML+acknowledgment expectation**: Use `mcp__vikunja__list_projects` and `mcp__vikunja__create_project` MCP tools (Executor's comprehension-gate iter-2 acknowledgment 3).
- **What was done**: Direct REST calls via `Invoke-RestMethod` — `POST /api/v1/login` to obtain bearer token (credentials read from `.vscode/mcp.json` since `VIKUNJA_PASS` was not in the Executor process env and no `.env` file exists at BlarAI root), then `GET /api/v1/projects` and `PUT /api/v1/projects`.
- **Reason**: The Executor session (GitHub Copilot Chat) had `mcp__vikunja__*` tools listed as deferred but no `tool_search` mechanism in the callable toolset to surface them; MCP path was not invocable in this session. REST path uses the identical Vikunja API the MCP server wraps, with the identical credentials, producing byte-identical server-side effects.
- **Why safe**: REST endpoints are the same surface the MCP `vikunja` server calls internally. Credentials read read-only from `.vscode/mcp.json` (not modified). Created project (id=10, title=DevPlatform-Meta) is identical to what the MCP path would have created.
- **Follow-up**: For Stage 2+ Executor sessions, either (a) ensure the Executor surface has MCP Vikunja tools loaded before comprehension-gate approval, or (b) update stage XMLs to permit REST-or-MCP at Executor's discretion with credential source explicitly named (`.vscode/mcp.json mcpServers.vikunja.env.VIKUNJA_PASS`).

### A3 — `Agents Cadence Monitor` S4U elevation requirement (Stage 0, work item 0.7) — HIGH

- **What was different**: 12 of 13 fleet tasks disabled cleanly in non-elevated PowerShell. `Agents Cadence Monitor` failed with `Access is denied` because its LogonType is **S4U** (Service for User), while the other 12 are **Interactive**. S4U tasks require an elevated shell to modify.
- **What was done**: Lead Architect opened elevated PowerShell and ran `Disable-ScheduledTask -TaskPath '\BlarAI\' -TaskName 'Agents Cadence Monitor'`. Verified `State=Disabled`. All 13 tasks now Disabled.
- **Why safe**: LogonType was not changed — preserves S4U property for post-cutover behavior. No semantic change to the task.
- **Implication for Stage 4 (CRITICAL)**: `Unregister-ScheduledTask` + `Register-ScheduledTask -Xml` for `Agents Cadence Monitor` at Stage 4.7 will also require elevation. The Stage 4 Executor MUST open an elevated shell for that task's re-registration, OR pre-disable in non-elevated shell and elevate only for Unregister+Register. Do NOT enter Stage 4's destructive block without anticipating this.
- **Follow-up**: Post-soak investigation of why `Agents Cadence Monitor` is S4U while every other fleet task is Interactive. May be intentional (cadence flipper needs to fire regardless of login state). Capture rationale in a DevPlatform-Meta Vikunja ticket per Stage 6.7.5 pattern.

### A6 — Stage 2 XML _project_context.py + preflight regex defects (Stage 1 close + 1) — LOW (fixed)

- **What was different**: Stage 2 XML item 2.2 inline _project_context.py used `registry.get("blarai")` but Stage 1.5's prescribed yaml schema is `blarai_project_id: 3` (Risk F1 surfaced by Guide instance 2 at Stage 1 closure review). Same key-mismatch defect appears in the regex `'blarai:\s*(\d+)'` used at Stage 2.8 / 3.7 / 4.7 BLARAI_PID preflight (Risk F3).
- **What was done**: Between-stages cleanup commit on `chore/platform-extraction` generalized _project_context.py resolve() to derive the lookup key from `root.name` (works for BlarAI today and any future project), and updated all three preflight regexes to `'blarai_project_id:\s*(\d+)'`. No code yet exists in the repo (Stage 2 EA writes _project_context.py at item 2.1); the XML defect would have caused ValueError at first runtime call.
- **Why safe**: Edits are to locked planning artifacts (stage XMLs) between stages, with explicit Lead Architect authorization. Stage 1 closure status unchanged. Stage 2 EA will paste the corrected code.
- **Follow-up**: None.

### A7 — `<vikunja_access_protocol>` codification at Stages 2, 3, 4 (Stage 1 close + 1) — LOW (procedural amendment)

- **What was different**: Stage 1 EA hit MCP-tool unavailability in the Executor surface and fell back to REST (Anomaly A5). Without codification, every subsequent Vikunja-touching stage would re-discover the same gap and re-file an A5-style anomaly.
- **What was done**: Added a `<vikunja_access_protocol>` block (immediately after `</comprehension_gate>`) at Stages 2, 3, 4 documenting MCP as preferred and REST as documented fallback, with credential source named at `C:\Users\mrbla\BlarAI\.vscode\mcp.json` (`mcpServers.vikunja.env.VIKUNJA_PASS`).
- **Why safe**: Both paths are byte-equivalent server-side. Neither bypasses Master Plan section D.1 enforcement (which is for fleet RUNTIME, not stage execution).
- **Follow-up**: None.

### A8 — agent_gates_bus reclassification (Stage 1 close + 1) — LOW (registry hygiene)

- **What was different**: Stage 1 EA recorded Vikunja `project_id=6` ("BlarAI Agent Gates") under `blarai_auxiliary_projects` in `devplatform/projects/registry.yaml`. Per BlarAI/CLAUDE.md section Vikunja Conventions, project 6 IS the Agent Gates bus — a fleet-level shared resource referenced by labels 9-14 — not a BlarAI auxiliary.
- **What was done**: Promoted to top-level `projects.agent_gates_bus` alongside `fleet_reports` in registry.yaml. Vikunja-side project name unchanged.
- **Why safe**: Registry classification only. No Vikunja API calls. Future devplatform_meta gate-state postings will land at the correct project.
- **Follow-up**: Optional — Stage 6 hardening could rename the Vikunja project from "BlarAI Agent Gates" to "Agent Gates" via `mcp__vikunja__update_project` for naming hygiene. Not required.

### A9 — architecture_decisions promotion to fleet-level (Stage 1 close + 1) — LOW (registry classification)

- **What was different**: Stage 1 EA recorded Vikunja `project_id=5` ("Architecture Decisions") under `blarai_auxiliary_projects` in `devplatform/projects/registry.yaml`. The Vikunja project name has no project prefix (unlike `BlarAI Infrastructure`, `BlarAI Drafts`, etc.), strongly suggesting cross-project / fleet-level intent for ADR (Architecture Decision Record) tracking.
- **What was done**: Promoted to top-level `projects.architecture_decisions` alongside `fleet_reports` and `agent_gates_bus` in registry.yaml. Vikunja-side project name unchanged.
- **Why safe**: Registry classification only. No Vikunja API calls. If Stage 6 investigation turns up evidence that this project is actually BlarAI-specific, re-classification is a one-line revert.
- **Follow-up**: Stage 6 hardening should confirm classification by inspecting actual ADR content in the Vikunja project. Specifically: if all ADR tasks reference BlarAI-internal architecture (Hyper-V, OpenVINO, USE-CASE-XXX), re-demote; if any reference fleet/platform/devplatform_meta, the fleet-level classification stands.

### A10 — blarai_auxiliary_projects provisional-classification notes (Stage 1 close + 1) — LOW (registry hygiene)

- **What was different**: After A8 (`agent_gates_bus` promotion) and A9 (`architecture_decisions` promotion), the `blarai_auxiliary_projects:` map has three remaining entries: `blarai_infrastructure: 4`, `blarai_fleet_dashboard: 7`, `blarai_drafts: 9`. Their actual usage (task counts, last-update dates) was not investigated at Stage 1 because that requires starting Vikunja and is out of scope for between-stages cleanup.
- **What was done**: Annotated each entry with YAML comments documenting provisional classification basis, ambiguity (notably project 7 "BlarAI Fleet Dashboard"), and a Stage 6 hardening directive to query Vikunja and decide keep/archive/reclassify per project. Schema stays as `key: int` — no structural change for future tooling reading the auxiliaries map.
- **Why safe**: Comments only; no behavioral change. Future tooling reads the same int-valued keys. Premature reclassification or archive without task-count data could drop active work.
- **Follow-up**: Stage 6 EA should: (a) start Vikunja temporarily, (b) call `list_tasks` (or REST equivalent per `vikunja_access_protocol`) for each of project 4, 7, 9, (c) decide per project: keep / archive / reclassify, (d) update `registry.yaml`, (e) stop Vikunja again. Optionally create a DevPlatform-Meta investigation ticket per the existing 6.7.5 pattern if deferring further.

### A11 — alias-vs-rename: `--project-root` exposed as alias of `--blarai-root` rather than rename (Stage 2, work item 2.4 / 2.7.v2 V4 authoring) — LOW (procedural classification)

- **What was different**: Stage 2 XML item 2.4 prescribes adding a `--project-root` flag to fleet entrypoints, with the implication (and the Guide-#5 v3 review's initial reading) that the existing `--blarai-root` flag would be RENAMED to `--project-root` at the same time. EA-3 (Stage 2.4 implementer) instead added `--project-root` as an ALIAS alongside the preserved `--blarai-root`, leaving both flag spellings functional.
- **What was done**: Both flags accepted at parse time; both resolve to the same `ProjectContext` constructor argument. The V4 V matrix test (`tools/tests/test_v_matrix_v4_cli_flag.py`, 12 cases) asserts byte-identical behavior between `--project-root` and `--blarai-root` invocations across all 13 entrypoints.
- **Why safe**: Backward-compatible by construction. No external caller breaks; new callers can adopt `--project-root` immediately; old `--blarai-root` callsites can migrate at their own pace. Default-preservation invariant V8 holds (no change to default-arg semantics when neither flag is passed).
- **Why classified anomaly (not pure decision)**: The procedural intent in Stage 2 XML 2.4 was rename; EA-3's deviation to alias was a deliberate scope-conservative interpretation surfaced by Guide-#5 at v3 review. The deviation is recorded as anomaly per dn3 "any procedural-vs-implementation gap is anomalable." Disposition: ACCEPT alias-as-deviation; rename optional at Stage 6 hardening if naming hygiene benefit outweighs migration cost.
- **Follow-up**: Stage 6 hardening may optionally rename (deprecate `--blarai-root` with a `DeprecationWarning`-equivalent stderr line, then remove at Stage 6.9 archive). Not required.

### A12 — Stage 3 EA identifier drift (`EA-1` and `g7-ea1_n13` labels in Guide-#7 verdict for the Stage 3 EA who is globally EA-7) — LOW (procedural / posterity-cleanup)

- **What was different**: The Stage 3 EA identifier convention is EA-7 (Stage 1 = EA-1; Stage 2 = EA-2..EA-6; Stage 3 = EA-7). The Guide-#7 verdict file labels the Stage 3 EA as `EA-1` throughout and the third-arbitration acknowledgment as `g7-ea1_n13` (with prior numbers `g7-ea1_n11`, `g7-ea1_n12`). Both labels inherit from a prior-session usage error and are documentation defects against the global EA-numbering convention.
- **What was done**: Per the no-amend doctrine for committed audit artifacts, the verdict file labels are NOT retroactively rewritten. Stage 3 execution restated the acks VERBATIM as labeled in the verdict file (`g7-ea1_n11`, `g7-ea1_n12`, `g7-ea1_n13`) for traceability. The naming correction folds into Stage 6.7.5 TICKET A's posterity-cleanup scope (DevPlatform-Meta investigation pattern; non-blocking).
- **Why safe**: The numerical sub-clause sequence and content of each ack are correct and binding; only the EA-numerical-suffix in the prefix is mislabeled. Tracking via verbatim restatement preserves auditability.
- **Follow-up**: Stage 6.7.5 TICKET A pickup will add a posterity-correction note + cross-reference table mapping `g7-ea1_n*` → `g7-ea7_n*`. No code or registry change required.

### A13 — Stage 3.3 expansion: `F3_BASH_FORK_ERROR_RUNBOOK.md` path-relocation (BlarAI `docs/` → devplatform `docs/runbooks/`) — LOW (scope expansion accepted)

- **What was different**: The original Stage 3.3 docs scope (g7-ea1_n12) covered `docs/runbooks/` selective copy of 12 fleet-relevant runbooks. During Item 3.8 forward+inverse drift verification (n13(h)), one additional file surfaced as Stage-3 candidate: `F3_BASH_FORK_ERROR_RUNBOOK.md` lives at BlarAI `docs/F3_BASH_FORK_ERROR_RUNBOOK.md` (top-level), not under `docs/runbooks/`. Mechanical co-location at `docs/runbooks/F3_BASH_FORK_ERROR_RUNBOOK.md` on the devplatform side requires path relocation, not a 1:1 path copy.
- **What was done**: Accepted as legitimate Stage 3.3 expansion-with-relocation. The file lands at `devplatform/docs/runbooks/F3_BASH_FORK_ERROR_RUNBOOK.md` (relocated). The devplatform-side `docs/runbooks/` count therefore is 12 BlarAI-source-runbooks + 1 relocated F3 = 13 files. Recorded in `.copy_manifest_v2.yaml` v2 entry for `docs/runbooks/`. Stop_condition (iv) NOT triggered after corrected inverse-verify.
- **Why safe**: F3 runbook is operationally fleet-scoped (bash fork error mitigation applies to fleet wake_launcher, not BlarAI-internal use cases). Relocation co-locates it with peer runbooks at devplatform `docs/runbooks/`. BlarAI-side copy left in place per BlarAI-side read-only invariant; Stage 5 cleanup may remove the BlarAI-side copy at the same time it removes the migrated tools/ directories.
- **Follow-up**: Stage 5 cleanup (`docs/platform_separation/06_STAGE5_CLEANUP.xml`) `keep_in_blarai` decision for `docs/F3_BASH_FORK_ERROR_RUNBOOK.md`: candidate for removal once devplatform `docs/runbooks/F3_BASH_FORK_ERROR_RUNBOOK.md` is live. Add to Stage 5 candidate-removal list at Stage 5 EA pickup.

### A14 — Stage 3 selective governance subset (4 of 17) + Stage 3.3 docs expansion scope acknowledgment — LOW (scope-conservative selection)

- **What was different**: Per g7-ea1_n12, the Stage 3 docs/ copy scope is intentionally selective — 4 of 17 governance documents in `docs/governance/` are fleet-relevant (`STYLE.md`, `fleet-hygiene.md`, `merge-policy.md`, `parallel-sprints.md`); the remaining 13 are BlarAI-internal architectural governance (USE-CASE policies, ADR templates, etc.) and stay at BlarAI. Additionally, Stage 3.3 (governance pack expansion beyond the original 3.1+3.2 scope) added Claude / CO_LEAD / Domain governance documents (CLAUDE_*, CO_LEAD_ARCHITECT_INITIATION_*.xml, DOMAIN8_*, DOMAIN9_*, DEC12/13/14.5/15 proposals, claude_projects/, claude_cowork/, governance/) to the devplatform copy.
- **What was done**: 4-of-17 selection encoded in `.copy_manifest_v2.yaml` v2 entry for `docs/governance/`. Stage 3.3 expansion documents enumerated under v2 entries `docs/CLAUDE_*`, `docs/CO_LEAD_*`, `docs/DOMAIN*`, `docs/DEC*`, `docs/claude_projects/`, `docs/claude_cowork/`. Items 3.1 (tools), 3.2.v2 (docs selective base), and 3.3 (docs expansion) are all dispositioned under acks g7-ea1_n11 + g7-ea1_n12 + g7-ea1_n13.
- **Why safe**: Selective scope avoids polluting devplatform with BlarAI-internal architectural governance. The 4 selected governance files are pure-fleet-process documents (style, hygiene, merge-policy, parallel-sprints) with no BlarAI Use-Case coupling. Stage 3.3 expansion documents are all fleet-process or Claude-agent-coordination materials applicable across both BlarAI and future devplatform-managed projects.
- **Follow-up**: Stage 6.7.5-pattern DevPlatform-Meta ticket may revisit the 13 BlarAI-retained governance documents at Stage 6 hardening if any later prove fleet-scoped after operational soak. No action required at Stage 3 close.

### A15 — Terminal-display-lag during elevated PowerShell 5 paste-relay (Stage 4 Item 4.8 n3(k)) — LOW (cosmetic)

- **What was different**: During Item 4.8's n3(k) elevation paste-relay carve-out for the 3 tasks with `<Enabled>false</Enabled>` in source XML (Agents Cadence Monitor S4U, Credentials Rotation Reminder, Escalation Watchdog), the elevated PowerShell 5 terminal display occasionally lagged behind actual command execution.
- **What was done**: LA verified each Unregister+Register paste-relay outcome via fresh terminal sessions (`Get-ScheduledTask -TaskName ... | Format-List`) rather than relying on the elevated PowerShell session's scrollback. All 3 tasks confirmed State=Ready post-Stage-4.
- **Why safe**: Display lag is cosmetic — the TaskScheduler API state is authoritative and was queried fresh. No state corruption; no missed verifications.
- **Follow-up**: None — cosmetic only.

### A16 — BUG 5 fail-OPEN cost-bleed risk (Phase C, post-Stage-4 close) — HIGH (prevented by LA risk-check)

- **What was different**: F-1 fix (n1(g)) replaced `.mcp.json` literal `VIKUNJA_PASS` with `${env:VIKUNJA_PASS}` template so VS Code's MCP loader could expand at server-launch time. **VS Code's MCP loader handles template expansion. PowerShell's `ConvertFrom-Json` does NOT.** Five PowerShell scripts that read `.mcp.json` directly (`wake_launcher.ps1`, `agents-cadence-monitor.ps1`, `escalation_watchdog.ps1`, `la_merge_approve.ps1`, `test_async_post_gate.ps1`) saw literal `${env:VIKUNJA_PASS}` string as password → Vikunja login failed with "Wrong username or password" code 1011.
- **Critical path**: `wake_launcher.ps1` lines 380-394 take a **fail-OPEN** branch when Vikunja login fails — invokes claude on every wake-* firing regardless of work-pending status. Estimated overnight cost if undetected: ~$58 (4 wake-* roles × 4 firings/hour × 8 hours × ~$0.45/invocation).
- **What was done**: LA's pointed risk-check question prevented the cost bleed: *"We should only see the powershell and python scripts running but no claude instances, is that correct?"* → emergency re-pause of state.json before next firing window → Phase B investigation confirmed root cause → Phase C1 reverted `.mcp.json` template → literal (sourced from User-scope env var, 23 chars). All 5 PS1 scripts now resolve credentials correctly without code changes.
- **Why safe (post-fix)**: Plaintext password in `.mcp.json` is gitignored per Ticket I (long-standing). VS Code MCP loader still works (literals supported, expansion is optional). Python remained unaffected throughout (`vikunja_mcp/cli.py` reads env vars directly per Item 4.11a CLI smoke evidence).
- **Follow-up**: Tickets II + JJ bound to Stage 6.7.5 — refactor 5 PS1 scripts to read VIKUNJA_USER/PASS/URL env vars directly (matches Python pattern). Once II is done, BlarAI/.mcp.json can revert back to template format safely. JJ is the consistency check on devplatform/.mcp.json template state.

### A17 — STATUS.md duplication via append, Item 4.13 n3(l) surgical truncate — LOW (root cause AMBIGUOUS)

- **What was different**: Item 4.13 STATUS append produced a duplicated "Stage 4 COMPLETE — 2026-04-28" section (each subsection appearing 2x in the file). Forensic investigation could not converge on a definitive root cause: helper file containing the append text was 3,480 bytes single-copy; `[System.IO.File]::AppendAllText` logged invocation once; diff vs prior STATUS.md showed duplicate addition.
- **What was done**: n3(l) ack directed surgical truncate at the second "## Stage 4 COMPLETE" marker preserving the first occurrence verbatim. STATUS.md restored to single-copy state at 5965f6b.
- **Why safe**: Single-copy invariant restored before Stage 4 closure record (this commit) overlays Phase C addendum. No risk of cascaded duplication.
- **Follow-up**: Stage 6.7.5 ticket — investigate AppendAllText behavior on Windows + UTF-8 BOM/encoding intersections; consider switching to `Add-Content -NoNewline` or hash-verified append helper for future STATUS appends.

### A18 — Subagent verification false-negative (Stage 4 dispatch audit; Ticket X bound) — LOW (procedural)

- **What was different**: 3 subagents invoked at different points during Stage 4 dispatch authoring reported "source XMLs have BlarAI paths" (suggesting cutover incomplete or mis-authored) when actual `git diff` showed the source XMLs were already migrated to devplatform paths or that retained BlarAI paths were intentional (e.g., `-BlarAIRoot` argument default, project-context lookup).
- **What was done**: Each false-negative was caught by Guide-#8 cross-checking subagent claims against actual `git diff` before accepting. No false-negative propagated into a committed dispatch.
- **Why safe**: Discipline of cross-verifying subagent reports before action prevented downstream errors. Pattern documented for Stage 5+ supervisors.
- **Follow-up**: Ticket X bound to Stage 6.7.5 — formalize subagent verification protocol for Guides supervising stage execution: never accept subagent claim about file state without `git diff` cross-check.

### A19 — BUG 1 wake_launcher reads stale BlarAI state.json (Phase C4 remediation) — MEDIUM (root cause + fix)

- **What was different**: Initial Stage 4 closure (Item 4.13) showed wake-* tasks reporting `LastTaskResult=4` (fleet_paused exit code per n3(j) acceptance) even after `devplatform/tools/autonomy_budget/state.json` was set to `fleet_paused=false` at Item 4.13.5. Initially attributed to first-firing race condition.
- **Real root cause** (uncovered via LA's continued pointed questioning): `wake_launcher.ps1` line 809 used `$RepoRoot` (= `-BlarAIRoot` arg value) for the state.json path → reading BlarAI's stale `tools/autonomy_budget/state.json` (still paused from Stage 0.0 v2 fleet pause; never updated through Phase 4) instead of devplatform's authoritative state.json. Same pattern affected line 69 (`$LogsDir`), causing logs to be written to BlarAI's `tools/scheduled-tasks/logs/` (BUG 4 — would be deleted at Stage 5.1 cleanup).
- **What was done (Phase C3 + C4)**: Line 69 changed from `$LogsDir = Join-Path $RepoRoot 'tools\scheduled-tasks\logs'` to `$LogsDir = Join-Path $PSScriptRoot 'logs'`. Line 809 changed from `$StateFile = Join-Path $RepoRoot 'tools\autonomy_budget\state.json'` to `$StateFile = Join-Path (Split-Path $PSScriptRoot -Parent) 'autonomy_budget\state.json'`. Both now resolve via `$PSScriptRoot`-derivation, decoupled from `-BlarAIRoot` arg. wake_launcher reads devplatform's authoritative state.json + writes logs to devplatform's log location (survives Stage 5.1).
- **Log migration (one-time)**: 820 unique BlarAI logs (pre-fix) migrated to `devplatform/tools/scheduled-tasks/logs/` for historical preservation pre-Stage-5.
- **Why safe (post-fix)**: 32 wake-* firings + 24 cadence_monitor firings observed clean across 1h45m soak window 9:15→11:00 EDT. Zero fail-open claude invocations. State markers stable.
- **Follow-up**: Ticket KK bound to Stage 6.7.5 — `BlarAI/tools/autonomy_budget/state.json` now dead artifact (still on disk, intentionally paused; not read by any active consumer). Stage 5.1 deletes parent directory; KK is auto-resolved when Stage 5.1 runs.

---

## Stage 2 Closure Footnotes

The twelve footnote items below cumulatively trace every disposition decision that landed inside the single Stage-2 commit `3d1ac35`. Each is a compact pointer to the substantive record in `docs/platform_separation/temp_for_responses/` (Guide reviews) and `docs/platform_separation/ea_outputs/` (EA mid-stage handoffs v1–v5 + completion reports + verification evidence). All twelve are required per ack g5-10 + corollary + g6-ea6_n7/n8/n9.

### 1. A11 alias-vs-rename anomaly
See Anomaly A11 above. EA-3 added `--project-root` as alias of `--blarai-root` rather than rename; Guide-#5 v3 review surfaced; LA accepted; V4 (12 cases) asserts byte-identical behavior. Optional Stage 6 cleanup.

### 2. g5-7 — duplicate test cleanup
Guide-#5 disposition file `2.4-GUIDE_RESPONSE_INSTANCE_5_VERIFICATION_OF_EA_4_F1_AND_2.5_WITH_ADJUSTMENTS.xml`: EA-4 inadvertently introduced two pairs of duplicate test definitions in `tools/tests/test_vikunja_client_scope.py` (`test_require_project_id_rejects_zero` + `test_require_project_id_rejects_negative`, each duplicated at lines 76–94). Disposition: delete the duplicate copy block at lines 76–94. Closed at EA-4 corrections cycle following Guide-#5's APPROVED_WITH_ADJUSTMENTS verdict.

### 3. g5-8 — env-fallback default in 6 PS1 scripts
Guide-#5 disposition: 6 PowerShell helpers (wake_launcher, toast_watchdog, etc.) needed `BLARAI_ROOT` env-fallback when `-BlarAIRoot` parameter not supplied. Order of resolution: explicit `-BlarAIRoot` > `BLARAI_ROOT` env > script's repo-root inference. Implemented at EA-4; V5 V matrix test asserts.

### 4. g5-9 — `$McpConfigPath` derivation
Guide-#5 disposition: scripts referencing `.mcp.json` (or per-IDE MCP configs) needed deterministic derivation of `$McpConfigPath` from the resolved BlarAI root rather than hard-coded literal paths. Implemented at EA-4; covered by the broader PS1 audit chain.

### 5. g5-10 — self-acknowledgment recorded as A11
Guide-#5 self-acknowledgment that the alias-vs-rename pattern in Item 2.4 had been flagged at v3 review and required formal anomaly recording. Discharged at this STATUS append: see Anomaly A11 above.

### 6. f1 — chokepoint helper fix + LA authorization via Guide-#5
Disposition log: `tools/_vikunja_client.py` initial implementation had a subtle scope-resolution bug (project_id was being read from a closed-over outer scope rather than the constructor-injected `ProjectContext`). Surfaced at EA-3 → diagnosed by Guide-#5 → fix authorized by LA via Guide-#5 disposition channel → applied at EA-4 → verified at EA-5 V matrix authoring. Now in `3d1ac35` baseline.

### 7. encoding regression footnote
During EA-4's Item 2.5 PS1 corrections cycle (specifically `la_merge_approve.ps1` + `agents-cadence-monitor.ps1` `McpConfigPath` comment edits), a transient UTF-8-BOM encoding regression was inadvertently introduced. EA-4 self-caught and fixed in the same iteration before Guide-#5 review (commended at Guide-#5 disposition file `2.4-GUIDE_RESPONSE_INSTANCE_5_F1_AND_2.5_CORRECTIONS_APPROVED.xml`, check id=`encoding_regression_self_caught`). No code-behavior change; cosmetic only.

### 8. 2.5.v2 closure pointer
Item 2.5 was re-executed at v2 (hence `2.5.v2`) after Guide-#5 v3 review identified gaps in the original 2.5 evidence. Closure artifacts: `scripts/verify_25_v2.ps1` (verification script) + `docs/platform_separation/ea_outputs/EA_2.5.v2_VERIFICATION_EVIDENCE.txt` (captured run output). Both committed at `3d1ac35`.

### 9. v4 documentation correction footnote (D2)
Guide-#5 v4 quality review identified a documentation-only defect (D2): EA-4's mid-stage handoff XML v4 misstated the count of refactored entrypoints by ±1 due to inclusion/exclusion edge case on a deprecated CLI. Corrected at v5 emission; no code change.

### 10. v5 documentation correction footnote (C1–C4)
Guide-#6 review of v5 mid-stage handoff identified 4 documentation defects: C1 = `count_delta` misattribution between two diff sections; C2/C3/C4 = three minor doc defects (typo, line-count mismatch in Adds block, stale stash-cycle count). All corrected in EA-6's commit-message synthesis at Item 2.9; no code change.

### 11. Option A architectural decision (D2-completion hoist) + g5-4 SATISFIED
Guide-#5 disposition g5-4 (file `2.4-GUIDE_RESPONSE_INSTANCE_5_VERIFICATION_OF_EA_2.4_PARTIAL.xml`): legacy `tools/fleet_observability/_vikunja_client.py:28` had a zero-arg `config_loader.load_config()` call that would auto-resolve to the wrong project overlay post-Stage-4 cutover when invoked from devplatform cwd. EA-5 made the load_config conditional at v5 (D2-PARTIAL). EA-6 closed at Item 2.6 D2-completion via Guide-#6 Option A AUTHORIZED disposition (file `2.6-GUIDE_RESPONSE_INSTANCE_6_CFG_RESOLUTION_DIVERGENCE_DISPOSITION_OPTION_A_HOIST.xml`): hoisted `cfg = config_loader.load_config(...)` above the `LiveVikunjaClient` constructor in 3 divergent files (`daily_digest`, `weekly_summary`, `run_live`); applied AFTER pattern `base_url=cfg['vikunja']['base_url']` uniformly across all 6 callers (3 client + 3 live; assignee-naming preserved per r1). g5-4 SATISFIED at Item 2.7 per Guide-#6 D2_COMPLETION_VERIFIED file. Now in `3d1ac35` baseline.

(NOTE: D3 is a SEPARATE disposition — `dashboard_maintainer.py:113` private-method `live._request` abuse closed via new public `update_task` method on `LiveVikunjaClient`. Both g5-4 and D3 landed at EA-6's D2/D3/D4 cycle but they are distinct dispositions targeting distinct files.)

### 12. g6-ea6_n7 + g6-ea6_n8 + g6-ea6_n9
- **g6-ea6_n7 — D1 NO-ACTION dispositions** (file `2.6-GUIDE_RESPONSE_INSTANCE_6_D1_NO_ACTION_DISPOSITIONS_AUTHORIZED.xml`): Item 2.6 D1 extended-grep verification net (12 patterns) surfaced two finding families outside the chokepoint-internal/legacy-shim-internal/test-only triage rule. Both authorized as NO-ACTION:
  - **F-D1-1**: `vikunja_mcp/` MCP-bus, 19 hits across `server.py` + `cli.py` + `bridge/daemon.py`. Acknowledged as third chokepoint family parallel to (a) `tools/_vikunja_client.VikunjaClient` for fleet-runtime scripts and (b) `tools/fleet_observability/_vikunja_client.LiveVikunjaClient` legacy. §D.1 enforcement preserved at function-level (server.py D4 DIVERGE-APPROVED: 7 `_require_project_id` sites at handler entry per docstring fix at 2.7.v2) + at user/protocol-input level (cli.py CLI flags; bridge/daemon.py inbox protocol). Class-method routing through `VikunjaClient` deferred to Stage 5+ when full chokepoint HTTP delegation is wired. Stage 6.7.5-pattern DevPlatform-Meta hardening ticket suggested.
  - **F-D1-2**: `openvino_contrib_agent` (urllib + GitHub PAT for GitHub API; not Vikunja). Out-of-domain by definition; Stage 5.1 `keep_in_blarai` list preserves `openvino_contrib_agent` in BlarAI permanently. No Stage 6 followup.
- **g6-ea6_n8 — V1–V7 closure V4 (vikunja_processes = 0) drift, Option B AUTHORIZED**: At Item 2.7 V1–V7 closure assertion run, V4 returned 1 (one `vikunja-v2.3.0-windows-4.0-amd64.exe` process running on host, PID 18304) where the V1–V7 closure assertion expected 0. EA-6 STOP-and-reported per Guide-#6 stop condition. Disposition: Option B AUTHORIZED — V4=1 is STATUS-staleness per Guide-#6 operating rule 5b(a), NOT procedure breakage. The V4=0 invariant came from Stage 1.4 step (e) closure (Vikunja stopped after MCP project-creation to restore Stage-0.4 quiesced state). The LA's operating environment has reasons to keep Vikunja running during the multi-day Stage 2 work cycle (parallel Guide/Co-Lead chats; manual webUI ticket work). Stage 2 XML does NOT require Vikunja stopped; Stage 2 work is pure code refactor (no Vikunja DB access). Stage 4 EA's preflight at item 4.1 has explicit fail-fast guard for V4=1 (`if ($running) { throw "Vikunja is still running. Stop it before migrating the DB." }`), so V4=0 will be enforced at Stage 4 cutover. Stage 2 close proceeds with V4=1 acknowledged. Disposition source: Guide-#6 review file `2.6-GUIDE_RESPONSE_INSTANCE_6_V4_VIKUNJA_PROCESS_DRIFT_OPTION_B_AUTHORIZED.xml`.

  (NAMESPACE NOTE: The V4 in this g6-ea6_n8 disposition is the V1–V7 CLOSURE assertion V4 from `EA_HANDOFF_STAGE2.xml` — a host-state check on `vikunja_processes` count. It is DISTINCT from the V matrix V4 in 2.7.v2, which is 'CLI flag exposure parametrized per refactored entrypoint' — a NEW pytest test with 12 cases at `tools/tests/test_v_matrix_v4_cli_flag.py` invoking `subprocess --help` over 6 argparse entrypoints. The two V4s share a label across distinct test/check namespaces; they are unrelated.)
- **g6-ea6_n9 — D4 docstring drift fix**: 3 docstring drift items + 1 optional clarification in `tools/vikunja_mcp/server.py` identified during Item 2.8 BLARAI_PID hard gate verification. Source-fix component COMMITTED at `3d1ac35` (this STATUS append discharges the FORWARD-ACTIVE component per Guide-#6 ack n=9 update).

---

## Stage 3 Closure Footnotes

The footnote items below cumulatively trace every disposition decision that landed inside the single Stage-3 commit `95884a0` on devplatform `main` (parent `3894221`). Each is a compact pointer to the substantive record in the Guide-#7 verdict files and the Stage 3 EA acknowledgment chain. All are required per the third-arbitration acks `g7-ea1_n11` + `g7-ea1_n12` + `g7-ea1_n13` (8 sub-clauses (a)–(h)).

### 1. Naming defect — `EA-1` / `g7-ea1_n*` labels in Guide-#7 verdict for the Stage 3 EA who is globally EA-7
See Anomaly A12 above. Verbatim ack labels (`g7-ea1_n11`, `g7-ea1_n12`, `g7-ea1_n13`) preserved per no-amend doctrine on committed audit artifacts. Posterity-correction folds into Stage 6.7.5 TICKET A scope.

### 2. g7-ea1_n11 — selective tools/+docs/ scope
Guide-#7 first arbitration: Stage 3 tools/ scope locked to 9 directories (autonomy_budget, fleet_observability, fleet_ops, gate_stale_cleaner, scheduled-tasks, vikunja_mcp, vikunja, _project_context.py, _vikunja_client.py); docs/ scope initially scoped to runbooks fleet subset + scheduled wake_templates. Stage 3 EA executed accordingly at Items 3.1 + 3.2.v2.

### 3. g7-ea1_n12 — governance selective subset (4 of 17) + Stage 3.3 expansion authorization
See Anomaly A14 above. 4-of-17 governance selection (STYLE, fleet-hygiene, merge-policy, parallel-sprints); Stage 3.3 expansion authorization for Claude / CO_LEAD / Domain governance pack. Encoded in `.copy_manifest_v2.yaml` per-directory v2 entries.

### 4. g7-ea1_n13 — eight sub-clauses (a)–(h) binding remaining Stage 3 amendments
- **(a) pyproject.toml dependency derivation**: Authored from empirical import-graph analysis of the 9 copied tools/ directories rather than guessed. Runtime deps: `httpx`, `pyyaml`, `mcp`, `jsonschema`. Test extras: `pytest`, `pytest-asyncio`. Discharged at Item 3.4.
- **(b) execution_ordering 9-step plan + 5 stop_conditions**: Items 3.4 → 3.4.5 → 3.5 → 3.6 → 3.7 → 3.8 → 3.10.v2 → 3.9 → 3.10 ordering enforced. Stop_conditions (i)(ii)(iii)(iv) NOT triggered at any step; (v) deferred to Stage 4 live-load smoke per (d).
- **(c) MCP / VS Code config copy** (3 sub-targets): Item 3.6 copied `.mcp.json` (top-level key `mcpServers`), `.vscode/mcp.json` (top-level key `servers`), `.vscode/tasks.json`. Per-file top-level keys preserved (NOT normalized) per (c). `VIKUNJA_PASS` plaintext literals replaced with `${env:VIKUNJA_PASS}` placeholders to keep secrets out of source control while preserving caller wiring.
- **(d) daily_digest --help non-destructive smoke**: Item 3.7 invoked `python -m tools.fleet_observability.daily_digest --help` and asserted exit 0. No Vikunja API calls made; full live-load smoke deferred to Stage 4 cutover preflight per stop_condition (v).
- **(e) `.gitignore` augment**: Item 3.9 appended 3 prescribed runtime-telemetry patterns (`tools/scheduled-tasks/logs/`, `tools/fleet_observability/escalation_seen.json`, `tools/fleet_observability/escalation_seen.json.tmp`) plus the editable-install metadata pattern (`devplatform.egg-info/`) discovered during pre-stage `git status` audit. Explicit allow-list `git add` (NOT `git add .`) used to stage Stage-3 commit, ensuring egg-info exclusion.
- **(f) F-N11 promotion of `tools/tests/` Class D → Class C**: Item 3.4.5 promoted V matrix tests at `tools/tests/test_v_matrix_v[4567]_*.py` plus `test_project_context.py` + `test_vikunja_client_scope.py` from Class D (transient verification scaffold) to Class C (committed test suite). 6 files entered `pytest --collect-only` count of 351 tests at Item 3.5.
- **(g) `.copy_manifest_v2.yaml` authorship**: Item 3.10.v2 authored a schema_version=1 manifest enumerating v1 baseline (10 dir-aggregate entries, parent commit 3894221) and v2 added files (21 dir-aggregate entries, totaling 195 v2 files). Validated via `yaml.safe_load`; manifest landed in same commit as Stage 3.9 staging per single-Stage-3-commit invariant.
- **(h) forward + inverse drift verification**: Item 3.8 ran forward grep (search devplatform-staged content for BlarAI-specific substrings) and inverse verify (compare BlarAI source vs devplatform copy line-by-line for the 9 tools/ + selective docs/ scopes). Forward grep: PASS (no `BlarAI` substring leaked). Inverse verify: PASS (selective-copy scopes confirmed); A13 F3 relocation surfaced and accepted as legitimate Stage 3.3 expansion-with-relocation.

### 5. Single-Stage-3-commit invariant + pre-stage state.json safety
189 files staged via explicit allow-list `git add docs/ tools/ pyproject.toml .mcp.json .vscode/ .gitignore .copy_manifest_v2.yaml`. Math: 195 v2_files − 8 gitignored runtime artifacts (7 logs/failures + 1 escalation_seen.json) + .gitignore + .copy_manifest_v2.yaml = 189. Pre-stage `tools/autonomy_budget/state.json` SHA256 `71FC1A2F21177F2461A750D0239244E709CF1E228778C46A6E188CC50D2D5D19` UNCHANGED across commit (verified post-commit); fleet pause invariant preserved.

### 6. BlarAI-side read-only invariant + Item 3.10 STATUS append exception
BlarAI source repo (branch `chore/platform-extraction` @ `3d1ac35`) was treated as read-only throughout Stage 3 execution per long-standing g7-ea1_n9 procedural exception, EXCEPT for this STATUS.md append (Item 3.10) which is the sole permitted BlarAI mutation. Append-only discipline: existing entries (Stage 0 / Stage 1 / Stage 2 ledger rows, anomalies A1–A11, Stage 2 Closure Footnotes 1–12, all prior Execution Log entries) are NOT modified. New rows / anomaly entries / footnotes / log entries APPENDED only.

---

## Stage 4 Closure Footnotes

The footnote items below cumulatively trace every disposition decision that landed inside Stage 4 cutover commits (`df3d940` cutover + `48df457` doc-drift sweep + `b9b213d` post-stage unpause + `be22a15` Phase C wake_launcher remediation + `751c3df` handoff-prep pause) plus the post-cutover Phase A/B/C/D remediation cycle (2026-04-29). Each is a compact pointer to the substantive record in Guide-#8 dispatch files (`docs/platform_separation/temp_for_responses/`) and the EA-8 acknowledgment chain.

### 1. Cumulative-ack chain (final, Stage 4 close)
- **g7-ea1_n10..n13** (Stage 3 inheritance; per A12 naming defect to be corrected at Stage 6.7.5 TICKET A)
- **g7-ea7_n14** (Stage 3.10 close)
- **g8-ea8_n1 (a..p)** — Stage 4 preflight audit + LA decisions including n1(c) DB stays at LocalAppData, n1(g) F-1 fix .mcp.json template, n1(l) split CLI smoke vs Claude Desktop smoke
- **g8-ea8_n2 (a..f)** — workflow simplification including n2(c) S4U paste-relay carve-out
- **g8-ea8_n3 (a..l)** — execution-time spec refinements:
  - n3(a-d): regex robustness + venv-stub filter + Pattern B' refinement
  - n3(e): Item 4.7.7 + 4.9 .lnk all-3-fields rewrite + null-safe field access
  - n3(f): 8 NEW Stage 4 work items
  - n3(g): vikunja_project_ids.yaml regex schema fix
  - n3(h): non-idempotency hardening discipline
  - n3(i): Item 4.7.7 sub-check (a) match refinement (deferred)
  - n3(j): Item 4.8 LastTaskResult fleet_paused exit-4 acceptance
  - n3(k): Item 4.8 elevation paste-relay carve-out (n2(c) precedent extended)
  - n3(l): Item 4.13 STATUS.md duplication surgical truncate
- **TOTAL: 116 binding atoms** at Stage 4 close (n3(l) increment over the original 115-atom count recorded in the Stage 4 COMPLETE marker section below).

### 2. Phase A — Cost-mitigation task disabling (LA directive, 2026-04-29)
LA directive after Phase C bug discovery: **5 scheduled tasks DISABLED** that were not actively used and posed cost-bleed or staleness risk: Welcome Back Poll, Daily Digest, Weekly Summary, Dashboard Maintainer, Toast Watchdog. **8 scheduled tasks remain ACTIVE**: Wake SDO, Wake Co-Lead Architect, Wake EA Code, Sprint Auditor, Agents Cadence Monitor, Credentials Rotation Reminder, Escalation Watchdog, Gate Stale Cleaner. Disabling executed via `Disable-ScheduledTask` (4 of 5) + elevated PowerShell (1 of 5 — Welcome Back Poll's S4U LogonType per A3 elevation precedent).

### 3. Phase B — BUG 5 root cause investigation
See Anomaly A16 above. F-1 template-vs-literal interaction with PowerShell `ConvertFrom-Json` direct readers identified across 5 affected PS1 scripts (wake_launcher, agents-cadence-monitor, escalation_watchdog, la_merge_approve, test_async_post_gate). Python (`vikunja_mcp/cli.py`) confirmed unaffected (reads env vars directly). Disposition: 3 options laid out in `temp_for_responses/PHASE_B_FINDINGS_PLUS_PHASE_C_OPTIONS.xml`; LA chose Option A (revert .mcp.json to literal) for fastest fix. Architectural cleanup deferred to Stage 6.7.5 Tickets II + JJ.

### 4. Phase C — Remediation execution
- **C1**: `BlarAI/.mcp.json` `VIKUNJA_PASS` reverted from `${env:VIKUNJA_PASS}` template to literal (sourced from User-scope env var, 23 chars). Manual Vikunja login test post-revert: SUCCESS. NOT committed (gitignored per Ticket I).
- **C2**: SKIPPED — original BUG 3 framing assumed logs would stay at BlarAI. With C3 architecture (relocate logs to devplatform), `daily_digest.py:99` `_DEVPLATFORM_ROOT` scan path is CORRECT.
- **C3 + C4**: 2-line edit in `devplatform/tools/scheduled-tasks/wake_launcher.ps1` per Anomaly A19 above. Committed at devplatform `be22a15`. 820 BlarAI logs (pre-fix) migrated to devplatform for historical preservation.

### 5. Phase D — Unpause + soak verification
- `devplatform/tools/autonomy_budget/state.json` unpaused at 13:06:02Z by guide_8_remediation. `BlarAI/tools/autonomy_budget/state.json` intentionally LEFT paused (dead artifact post-C4; auto-resolved at Stage 5.1 per Ticket KK).
- **Soak window**: 9:15 → 11:00 EDT (1h45m).
- **Verification metrics**:
  - 32/32 wake-* firings clean (4 roles × 8 cycles every 15 min): all WORK-GATE skip + NO-WORK-EXIT
  - 24/24 cadence_monitor firings silent (every 5 min; success path is silent per script design; no ABORT entries post-9:00:02)
  - 0 escalation_watchdog log entries (silent success path holding)
  - 0 fail-open claude invocations
  - 0 state.json mutations during soak
  - 0 new failures-dir entries
  - Runtime/platform isolation confirmed mid-soak by LA's BlarAI runtime launch + prompt response test (services/policy_agent + services/assistant_orchestrator unaffected by dev-platform extraction)

### 6. Stage 6.7.5 hardening backlog (final, Stage 4 close)
Tickets bound during Stage 4 cutover + Phase C remediation: **I, K, L, M, V, W, X, Y, Z, AA, BB, CC, EE, FF, GG, HH, II, JJ, KK** (19 tickets). Of these:
- **II** (NEW from Phase C): Refactor 5 PS1 scripts to direct env-var credential pattern (Python parity per `vikunja_mcp/cli.py` model). Allows BlarAI/.mcp.json to revert back to template format.
- **JJ** (NEW from Phase C): devplatform/.mcp.json template consistency check (decide per LA preference, paired with II).
- **KK** (NEW from Phase C): BlarAI/tools/autonomy_budget/state.json dead-artifact cleanup (auto-resolved by Stage 5.1).
- **A** (carried from Stage 3 A12): Posterity-correction note for `g7-ea1_n*` → `g7-ea7_n*` Stage 3 EA naming defect.

Reference: per-item dispatch artifacts in `docs/platform_separation/temp_for_responses/`.

### 7. BlarAI-side commit-discipline footnote
BlarAI's `chore/platform-extraction` HEAD remained at `5965f6b` UNCHANGED through Phase C remediation. Phase C work was entirely devplatform-side: 4 commits (`b9b213d`, `be22a15`, plus pre-existing `df3d940`/`48df457` for original Stage 4 cutover; `751c3df` handoff-prep pause). The `.mcp.json` revert (C1) was NOT committed because `.mcp.json` is gitignored per Ticket I. The state.json mutations (BlarAI re-pause, devplatform unpause/repause) were runtime data, not committed at Phase C close. BlarAI HEAD advances at this Stage 4 closure record commit and the subsequent Guide-#8 → Guide-#9 handoff XML commit.

### 8. Stage 4 transitions to Stage 5
Guide-#9 spawn handoff written at `GUIDE_HANDOFF_LATEST.xml` per the established Guide handoff convention (analog of Guide-#7 → Guide-#8 handoff at `b9a173d`). Stage 5 dispatch at `06_STAGE5_CLEANUP.xml` is read by Guide-#9 with **3 open scope decisions** noted (5.0.5 archive scope vs Phase-C-migrated logs reality, 5.9 fleet verification substitute given Phase A disabling of `BlarAI_daily_digest`, Tickets II/JJ confirmation as Stage 6.7.5 deferred). Guide-#9 to author updated Stage 5 plan + EA-9 init prompt for LA gate-review per the established planning-then-dispatch separation pattern.

---

## How to Resume After Interruption

1. Read this file first.
2. Read `00_MASTER_PLAN.md` for full context.
3. Check the "Next stage to execute" row at the top.
4. Open the corresponding stage XML file and attach to a fresh VS Code Copilot session.
5. Do the comprehension gate, get Lead Architect approval, then proceed.

## Item 4.7.5.E (Vikunja .zip preservation)
- Source: C:\Users\mrbla\BlarAI\tools\vikunja\vikunja-v2.3.0.zip
- Destination: C:\Users\mrbla\devplatform\tools\vikunja\vikunja-v2.3.0.zip
- SHA256: 3E7479DE6DBF2D2F3161358083BB9780E6FA7D8FCB8E2D29020FE234138834AD
- Size: 30090974 bytes
- Date: 2026-04-29T01:35:54Z
- Note: zip preserved in Stage 3 commit 95884a0 (devplatform); hash record retroactively appended in Item 4.7.5.E execution

## Stage 4 COMPLETE — 2026-04-28

Cutover from BlarAI-rooted to devplatform-rooted platform tooling completed. devplatform now authoritative for: Vikunja MCP server, scheduled-task scripts, autonomy_budget state, fleet_observability, fleet_ops, gate_stale_cleaner. BlarAI workspace + .platform/ + Vikunja DB (at LocalAppData) preserved.

### Vikunja DB hash (corruption detection baseline)
SHA256: 757C123FBC601D50E059C8E6D273B1A22F27C6952FEDB436A7B060DD139C7425
Path: %LOCALAPPDATA%\Vikunja\vikunja.db (per LA n1(c) decision — DB stays at LocalAppData; not in either repo)
Note: hash captured via FileShare.ReadWrite snapshot while Vikunja server held an open handle (live DB); SQLite WAL committed-but-uncheckpointed transactions may not be reflected in main .db file. Acceptable as a Stage-4-close baseline; future corruption checks should snapshot under the same convention for comparability.

### Re-enabled scheduled tasks (Item 4.8 + paste-relay carve-out per n3(k))
13/13 tasks at TaskPath \BlarAI\, all State=Ready post-Stage-4:

Initial enable batch (10/13 — n3(j) acceptance for fleet_paused exit code 4):
- Daily Digest, Gate Stale Cleaner, Toast Watchdog, Welcome Back Poll, Weekly Summary, Dashboard Maintainer (LastTaskResult=0, clean run)
- Wake SDO, Wake Co-Lead Architect, Wake EA Code, Sprint Auditor (LastTaskResult=4, fleet_paused — accepted per n3(j))

Paste-relay elevation batch (3/13 per n3(k); n2(c) precedent extended for tasks with `<Enabled>false</Enabled>` in source XML):
- Agents Cadence Monitor (S4U + explicit Enabled=false)
- Credentials Rotation Reminder (explicit Enabled=false)
- Escalation Watchdog (explicit Enabled=false)

### End-to-end smoke test evidence (Item 4.11a + n1(l) split)
Item 4.11a (EA-8 scriptable) — PASS via Option α (n1(l) wrapper defect Ticket FF):
- Invocation: `python -m tools.vikunja_mcp.cli list-projects` (corrected per Guide-#8 from spec wrapper)
- Exit code: 0
- Result: 9 projects returned via REST API → JSON parse, including:
  - BlarAI Core Development (id 3) ✓
  - Fleet Reports (id 8) ✓
  - DevPlatform-Meta (id 10) ✓
- Validates: devplatform venv → tools.vikunja_mcp module → REST → JSON parse end-to-end

Item 4.11b (LA manual Claude Desktop smoke) — DEFERRED to post-Stage-4 close per n1(l) split.

### Cumulative-ack chain (final)
- g7-ea1_n10..n13 (Stage 3 inheritance)
- g7-ea7_n14 (Stage 3.10 close)
- g8-ea8_n1 (a..p) — Stage 4 preflight audit + LA decisions
- g8-ea8_n2 (a..f) — workflow simplification including n2(c) S4U paste-relay carve-out
- g8-ea8_n3 (a..k) — execution-time spec refinements:
  - n3(a-d): regex robustness + venv-stub filter + Pattern B' refinement
  - n3(e): Item 4.7.7 + 4.9 .lnk all-3-fields rewrite
  - n3(f): 8 NEW Stage 4 work items
  - n3(g): vikunja_project_ids.yaml regex schema fix
  - n3(h): non-idempotency hardening discipline
  - n3(i): Item 4.7.7 sub-check (a) match refinement (deferred)
  - n3(j): Item 4.8 LastTaskResult fleet_paused acceptance
  - n3(k): Item 4.8 elevation paste-relay carve-out
- 115 binding atoms total

### Stage 6.7.5 hardening backlog
Tickets bound during Stage 4: I, K, L, M, V, W, X, Y, Z, AA, BB, CC, EE, FF
(Reference: per-item dispatch artifacts in docs/platform_separation/temp_for_responses/)

### Anomalies bound (Stage 4 execution)
A15 — terminal-display-lag during elevated PowerShell 5 paste-relay (cosmetic; no state corruption)

### Phase C addendum (2026-04-29 — post-cutover bug remediation)

The Stage-4-close marker above (2026-04-28) recorded the original cutover close. Post-cutover bug discovery 2026-04-29 surfaced 5 bugs (BUGs 1/2/4/5 fixed in Phase C; BUG 3 reclassified N/A given C3 architecture). 1h45m soak window 9:15→11:00 EDT verified clean operations post-remediation. Stage 4 declared **operationally CLOSED at 2026-04-29**.

Updates to the markers above:
- **Cumulative-ack chain** (above: "115 binding atoms total"): now **116 atoms** — n3(l) added at Item 4.13 STATUS.md surgical truncate. Full enumeration in Stage 4 Closure Footnotes §1 above.
- **Stage 6.7.5 hardening backlog** (above: "I, K, L, M, V, W, X, Y, Z, AA, BB, CC, EE, FF"): now **19 tickets** — GG (wake template path scan automation) + HH (scheduled-task XML re-registration paste-relay automation) bound at Stage 4 execution; II + JJ + KK bound at Phase C remediation. Full enumeration in Stage 4 Closure Footnotes §6 above.
- **Anomalies bound** (above: "A15"): now **A15-A19** — A16 (BUG 5 fail-OPEN cost-bleed risk; HIGH; prevented by LA risk-check question), A17 (STATUS.md duplication; root cause AMBIGUOUS), A18 (subagent verification false-negative), A19 (BUG 1 wake_launcher reads stale BlarAI state.json; MEDIUM). Full subsections in Anomalies / Deviations from Plan section above.
- **Phase A** (LA directive 2026-04-29): 5 of the 13 originally-re-enabled scheduled tasks were **DISABLED** for cost mitigation (Welcome Back Poll, Daily Digest, Weekly Summary, Dashboard Maintainer, Toast Watchdog). 8 ACTIVE remaining.

Stage 4 transitions to Stage 5 — Guide-#9 + EA-9 spawn pattern, with Stage 4 Closure Footnotes §8 above defining the handoff protocol.

---

## Stage 5 Closure Footnotes

The footnote items below cumulatively trace every disposition decision that landed inside Stage 5 (cleanup) commits — the pre-Item-5.10 working-tree state on `chore/platform-extraction` (cumulative deletes from Items 5.1+5.3+5.5+5.5.v2; cumulative edits from Items 5.6+5.7), the Item-5.10 single big BlarAI commit `3e73484` that captures all of those, the merge commit `4122b92` on BlarAI `main`, the post-merge tags (`post-platform-extract` on BlarAI `4122b92`; `platform-extracted` on devplatform `ae75507`), the 3 mid-execution devplatform commits (`1a552d9` pause + `c20e298` Phase E + `ae75507` Phase F), and the close-unpause commit on devplatform `main`. Each is a compact pointer to the substantive record in Guide-#9 dispatch files (`docs/platform_separation/temp_for_responses/`) and the EA-9 acknowledgment chain.

### 1. Cumulative-ack chain (final, Stage 5 close)
- **g7-ea1_n10..n13** (Stage 3 inheritance; per A12 naming defect; carry-corrected at g7-ea7_n14)
- **g7-ea7_n14** (Stage 3.10 close)
- **g8-ea8_n1 (a..p)** — Stage 4 preflight audit + LA decisions (16 sub-clauses; n1(a) SUPERSEDED-BY-n2(b) + n1(h) Step 4 REFINED-BY-n2(c) per Stage 4 supplement-2)
- **g8-ea8_n2 (a..f)** — Stage 4 workflow simplification (n2(a) Item 4.0 narrowed kill + n2(b) supersession + n2(c) S4U paste-relay carve-out + n2(d) prep-3 reframing + n2(e) surface directives + n2(f) iter-1 gate update)
- **g8-ea8_n3 (a..l)** — Stage 4 execution-time spec refinements (12 sub-clauses)
- **g9-ea9_n1 (a..n)** — Stage 5.0.v2 dual-track pre-flight audit + Pre-Flight Step 0 (14 sub-clauses; class breakdown A=1 LOAD-BEARING n1(e) + B=0 + C=8 + D=5; n1(n) Pre-Flight Step 0 rollback-readiness verification per Guide-#8 dispatch at 9e92b26)
- **g9-ea9_n2 (a..b)** — Stage 5 mid-execution remediation:
  - **n2(a)**: Phase E commit `c20e298` — 3 PS1 scripts (cadence_monitor + escalation_watchdog + toast_watchdog) Phase-C-BUG-1 pattern fix; mirrors wake_launcher Phase C be22a15
  - **n2(b)**: Phase F commit `ae75507` — wake_launcher.ps1 7 dynamic-path edits per Item 5.4 audit (3 LA Step-7 'tools' subpath + 4 broader-sweep 'docs' subpath); line 482 stagingDir verified correct as-is (resolves to BlarAI/docs/scheduled/ea_queue/staging which stays valid post-Stage-5)
- **TOTAL: 132 binding atoms** at Stage 5 close (130 inherited + 2 new under g9-ea9_n2(a-b)).

### 2. Phase E remediation (Stage 5 mid-execution)
Item 5.4 audit + LA Step (7) amendment surfaced 3 PS1 scripts in `devplatform/tools/scheduled-tasks/` with Phase-C-BUG-1 pattern (`Join-Path $RepoRoot 'tools\...'` defaulting to BlarAI):
- `agents-cadence-monitor.ps1`: $LogsDir → `Join-Path $PSScriptRoot 'logs'` (1 edit, line 28)
- `escalation_watchdog.ps1`: $seenPath + $notifier → `Join-Path (Split-Path $PSScriptRoot -Parent) 'fleet_observability\...'` (2 edits, lines 79 + 164)
- `toast_watchdog.ps1`: $flag + $consumed + $notifier → `Join-Path (Split-Path $PSScriptRoot -Parent) 'fleet_observability\...'` (3 edits, lines 20 + 44 + 48)

Total **6 edits in 3 scripts** committed at devplatform `c20e298`. Pattern mirrors Phase C be22a15 wake_launcher fix. `la_merge_approve.ps1` same pattern: deferred to Stage 6.7.5 Ticket II per LA option (b2) (DEC-14.5 motion logic overlap; environ-var refactor scope; documented + non-blocking).

LA paste-relays during Phase E: **#1** disable Agents Cadence Monitor S4U + LA also ran `Remove-Item -Recurse -Force C:\Users\mrbla\BlarAI\tools\scheduled-tasks` from same elevated shell to clear empty `logs/` residue (per A24); **#2** enable Agents Cadence Monitor S4U.

Validation soak: cadence_monitor + escalation_watchdog fired post-fix with LastTaskResult=0; **`escalation_seen.json` appeared at devplatform path** (`devplatform/tools/fleet_observability/escalation_seen.json` 65 bytes, 2026-04-30T02:50:02Z) — definitive proof of edit effectiveness; BlarAI/tools/scheduled-tasks did NOT recreate.

### 3. Phase F remediation (Stage 5 mid-execution)
Item 5.4 audit broader sweep (per t11/dn35 + LA Step (7) amendment) surfaced **8 dynamic-path drifts in `wake_launcher.ps1` beyond Phase C be22a15** (which fixed only lines 69 + 809). Phase F edited 7 lines (line 482 verified correct as-is):

- **Lines 299, 789, 793** → `$PSScriptRoot`-relative or `(Split-Path $PSScriptRoot -Parent)` (devplatform-side housekeeping)
- **Lines 344, 492, 833** → `Join-Path $RepoRoot 'docs\...'` (target-project; reverted to docs/ namespace at Stage 5.3 partial reversal devplatform commit `8b0ad16` 2026-04-30; was briefly `.platform\...` between Item 5.3 and the reversal)
- **Line 870** → `Join-Path (Split-Path (Split-Path $PSScriptRoot -Parent) -Parent) 'docs\scheduled\wake_templates\...'` (devplatform/docs/scheduled/wake_templates per Stage 3 copy)

**Line 870 was the GATING finding** — without Phase F fix, Item 5.5.v2 wake_templates wholesale-delete would have broken wake_launcher.ps1 with `exit 8` on every firing.

Committed at devplatform `ae75507`. **A29 anomaly bound**: Phase C be22a15 was incomplete — Phase F closes the remaining 7 dynamic-path drifts in wake_launcher.

Validation re-soak (6 min): cadence_monitor + escalation_watchdog fired LTR=0; `cadence_monitor_20260430.log` grew 0.08 → 0.16 KB at 4:00:03 minute=0 (script's once-per-hour log condition triggered; Phase E n1(c) implicitly verified through wake_launcher's chain); BlarAI/tools/scheduled-tasks did NOT recreate.

### 4. Item 5.5.v2 SELECTIVE governance delete (n1(e) Class A LOAD-BEARING DISCHARGE)
Per A14 disposition (Stage 3.2.v2 selective-copy decision: only 4-of-17 governance docs migrated to devplatform), Item 5.5.v2 SELECTIVELY deleted only the 4 migrated copies from BlarAI side, PRESERVING the 13 BlarAI-internal architectural governance docs:
- **DELETED (4)**: STYLE.md, fleet-hygiene.md, merge-policy.md, parallel-sprints.md
- **PRESERVED (13)**: README.md, circuit-breaker.md, configuration-management.md, context-spotlighting.md, deployment-verification.md, error-recovery.md, gpu-runtime.md, ipc-protocol.md, observability.md, pgov-validation.md, rule-engine.md, session-state.md, streaming-output.md

Wake_templates wholesale-delete UNCHANGED (6/6 fully migrated at Stage 3.2.v2; safe to delete BlarAI/docs/scheduled/wake_templates wholesale).

ack9 LOAD-BEARING confirmation gate: LA explicitly approved selective-delete plan; Class A risk surface (data loss for 13 BlarAI-internal docs that contain USE-CASE policies, ADR templates, hardware/runtime docs) MITIGATED. Dispatch line 30 unamended (still says wholesale `Remove-Item -Recurse -Force`); EA-9 executed n1(e) selective amendment, NOT dispatch literal, per ack9 + data-preservation default.

### 5. Item 5.0.5 audit archive
Forensic preservation per Workflow-Integrity-Review S-2 + dn32: **1499 files archived** from 6 about-to-be-deleted dirs (tools/fleet_ops, fleet_observability, autonomy_budget, gate_stale_cleaner, scheduled-tasks, vikunja_mcp) into `BlarAI/.platform/audit_archive/pre_stage5_20260430_013411.zip` (43 MB) BEFORE Item 5.1 deletion.

Per-pattern breakdown:
- `*.log`: 1496 files
- `state.json*`: 1 (BlarAI dead-artifact state.json)
- `lifts.json`: 1 (n1(a) extension; F.1 Option A "preserves stragglers")
- `escalation_seen.json`: 1 (n1(a) extension)
- `*.jsonl`, `*.json.bak`, `*.history`: 0 each (no matches; expected)

Archive zip path gitignored at Item 5.7 per n1(h) (large binary; forensic-only); contents preserved on disk under `.platform/audit_archive/` for 90-day retention per Master Plan §5.

### 6. Item 5.9 F.2 30-min mini-soak verification metrics
Soak window: **2026-04-30T03:40:26 → 2026-04-30T04:10:26 (29.83 min total)** via 4 chunked PowerShell calls (~9 min each within 10-min PowerShell tool timeout).

- **cadence_monitor + escalation_watchdog**: 4 firings each (every 5 min); ALL LastTaskResult=0
- **Wake-* tasks** (Wake SDO, Wake Co-Lead Architect, Wake EA Code) + **Sprint Auditor**: 2 firings each (every 15 min); ALL LastTaskResult=4 (fleet_paused exit-4 per n3(j) acceptance)
- **Non-firing tasks** (Credentials Rotation Reminder daily; Gate Stale Cleaner hourly): NOT fired in 30-min window per F.2 disposition (NOT a failure)
- **0 fail-open claude.exe invocations**; claude_processes=2 stable across 27+ polls. Cross-verified via `Get-CimInstance Win32_Process -Filter "Name='claude.exe'" | Select-Object ProcessId, ParentProcessId, CreationDate`: both have parent = pwsh.exe running VS Code shellIntegration.ps1 (ProcessId 10016 created 2026-04-29T16:34Z = prior session; ProcessId 24692 created 2026-04-30T00:10Z = EA-9 session). 0 wake_launcher.ps1-spawned powershell.exe processes found.
- **0 BlarAI watch path recreations** across 6 paths (`tools/scheduled-tasks`, `tools/fleet_observability`, `tools/autonomy_budget`, `docs/sprints`, `docs/active_tasks.yaml`, `docs/scheduled/wake_templates`) — verified at every 60s poll throughout 27+ polls + final
- **9 log files written DURING soak** at devplatform/tools/scheduled-tasks/logs/ (0 at BlarAI side): 4× wake-* role logs at 3:45:02 + 4× wake-* role logs at 4:00:02 + 1× cadence_monitor_20260430.log update at 4:00:03
- **`cadence_monitor_20260430.log` appeared + grew** (0.08 → 0.16 KB at 4:00:03 minute=0; script's once-per-hour log entry triggered when cadence_monitor sees minute < 5) — definitive proof of Phase E n1(c) cadence_monitor fix effectiveness
- **Vikunja API serving v2.3.0** throughout (devplatform PID 14156 unaffected by any Stage 5 work)

### 7. Stage 6.7.5 hardening backlog (final, Stage 5 close + post-close evolution + Stage-4-close enumeration gap recovery + Stage-5.3 reversal binding)
**36 tickets total** (28 at Stage 5 close per verdict snapshot; +1 post-close-discovered UU; +6 Stage-4-close enumeration gap recovered B/C/D/E/F/G per Vikunja-binding cross-verification 2026-04-30; +1 Stage-5.3 reversal cleanup VV bound 2026-04-30 post-spot-check):
- **26 inherited from Stages 0-4**: B, C, D, E, F, G, I, K, L, M, V, W, X, Y, Z, AA, BB, CC, EE, FF, GG, HH, II, JJ, KK, LL
- **1 carryforward from Stage 3**: TICKET A (g7-ea1_n* → g7-ea7_n* posterity correction per A12)
- **5 NEW from Guide-#9 cycle**: MM (dispatch + init pointer V0 doc-defects + ext2 strict-count refinement), OO (auto-running reports policy), PP (vikunja-autostart-shortcut.md doc update), QQ (13 BlarAI-internal governance docs review post-Stage-5; A14 follow-up), RR (fleet-status.ps1 on-demand audit script)
- **2 NEW Stage-5-discovered**: SS (zombie BlarAI Vikunja launch mechanism investigation per A23; Startup .lnk verified correct at `Vikunja (BlarAI).lnk` pointing devplatform per Stage 4.9 rewrite — launch mechanism remains unknown), TT (Item 5.4 audit-pattern enhancement per LA Step (7) amendment + posterity audit of remaining devplatform PS1 scripts not in Phase E/F scope)
- **1 NEW post-Stage-5-close**: UU (Vikunja-project rationalization — audit `devplatform/projects/registry.yaml` "cross-project" framing vs operational reality: project 5 "Architecture Decisions" has 5 tickets all BlarAI-scoped; projects 6 "BlarAI Agent Gates" + 7 "BlarAI Fleet Dashboard" are BlarAI-prefixed despite cross-project intent in registry; projects 1 "Inbox" + 9 "BlarAI Drafts" + 10 "DevPlatform-Meta" are zero-task placeholders. Decide: (a) consolidate ADR workflow into project 3 OR keep separate with explicit single-project rationale; (b) deprecate or accept the BlarAI-prefixed-but-framed-cross-project anomaly for projects 6/7; (c) cleanup or repurpose empty placeholder projects 1/9/10; (d) defer genuine cross-project Vikunja-bus structures until a 2nd project actually activates. ADR documents themselves at `BlarAI/docs/adrs/ADR-005..ADR-012` are git-tracked + safe regardless of Vikunja-side decisions. Bound at LA architectural discussion post-Stage-5-close 2026-04-30 post-verdict-emission.)
- **1 NEW Stage-5.3-reversal-cleanup**: VV (cross-repo path resolution audit + Stage 5.3 reversal cleanup — autonomy_budget DEFAULT_ROSTER_PATH cross-repo defect at `active_tasks.py:38` resolves to non-existent `devplatform/docs/active_tasks.yaml` instead of `BlarAI/docs/active_tasks.yaml`; pre-existing defect surfaced by Stage 5→6 boundary spot-check; HIGH priority; sub-items: (i) DEFAULT_ROSTER_PATH cross-repo discovery fix, (ii) docstring + README alignment audit across autonomy_budget + proactive_colead/sdo, (iii) end-to-end smoke test of /sprint-discovery + /sprint-debrief + /sprint-kickoff Phase 0 reads. Bound at LA spot-check 2026-04-30 pre-Guide-#10-spawn.)

**Stage-4-close enumeration gap recovery (B/C/D/E/F/G)**: Stage 3 close handoff (`temp_for_responses/3.10-GUIDE_HANDOFF_INSTANCE_7_TO_8.xml` lines 129-138) bound 5 tickets A-E. Stage 4 preflight audit (`temp_for_responses/4.0.v2-GUIDE_RESPONSE_INSTANCE_8_STAGE4_PREFLIGHT_AUDIT_CHECKPOINT.xml` lines 89, 836, 903) confirmed inheritance and added F + G to bring backlog to 7 tickets A-G + TICKET E sub-item expansion. Stage 4 close STATUS.md enumeration silently dropped B/C/D/E/F/G from inherited-list (line 469 originally listed only Stage-4-bound letters; Stage 5 close inherited from Stage 4 close enumeration without re-validation). Recovery 2026-04-30: tickets created in Vikunja project 10 DevPlatform-Meta with full origin-trail metadata; backlog count 29 → 35. None of B/C/D/E/F/G were retired or completed in committed artifacts; this is a documentation-defect recovery, not a re-binding. Per LA mature-not-minimal motto + `feedback_doc_cleanup_non_optional.md`, hardening followups are NON-OPTIONAL.

NN skipped per skip-the-cancelled-letter convention. Single letters F, G recovered (NOT skipped); single letters H, J, N, O, P, Q, R, S, T were never bound.

**Vikunja project location**: All 36 tickets bound to date created in Vikunja project 10 (DevPlatform-Meta) IDs 282-317 sequentially per the original Stage 3 plan (`temp_for_responses/3.0.v2-GUIDE_RESPONSE_INSTANCE_7_STAGE3_COMPREHENSIVE_AUDIT_CHECKPOINT.xml` line 643: "auto-created via mcp__vikunja__create_task in DevPlatform-Meta project (id=10) at Stage 6.7.5 EA execution"). Letter→ID mapping: A=282, I=283, K=284, L=285, M=286, V=287, W=288, X=289, Y=290, Z=291, AA=292, BB=293, CC=294, EE=295, FF=296, GG=297, HH=298, II=299, JJ=300, KK=301, LL=302, MM=303, OO=304, PP=305, QQ=306, RR=307, SS=308, TT=309, B=310, C=311, D=312, E=313, F=314, G=315, UU=316, VV=317.

Reference: per-item dispatch artifacts in `docs/platform_separation/temp_for_responses/` (Guide-#9 verdicts at 5.0.v2-* + 5.0-* rollback-readiness + 5.4-EA_INSTANCE_9_DEVPLATFORM_AUDIT_FINDINGS.md).

### 8. BlarAI-side commit-discipline footnote (Stage 5 commits + tags)
chore/platform-extraction tip pre-Item-5.10: `ff39a41` (init pointer commit). Item 5.10 single big BlarAI commit `3e73484` ("Extract platform layer to devplatform (Stages 2-5)") on `chore/platform-extraction` captures ALL Stage 5 destructive deletes + .platform/ moves + pyproject.toml + .gitignore edits.

**Single-commit shortstat** (`git show --shortstat 3e73484`): **335 files / +1120 / −33179**.

**Cumulative pre-merge diff** (`git diff --shortstat 4122b92^1..4122b92^2`, i.e. pre-merge `main` tip `3e5f439` to `chore/platform-extraction` tip `3e73484`): **480 files / +32942 / −37655** across **42 commits** ahead.

(EA-9's Stage 5 close report originally cited `477 files / +31831 / −53494; 39 commits` for the cumulative figure — minor numeric drift bound to Stage 6.7.5 Ticket MM scope per Stage 5 close verdict drift §1; numbers above reflect actual disk state per Guide-#9 cross-verification 2026-04-30T16:48Z post-MM-correction.)

Item 5.10 merge to main: `4122b92` ("Merge platform extraction to main") via `--no-ff`. **chore/platform-extraction branch PRESERVED post-merge** per copilot-instructions preservation rule (visible in `git branch` listing).

devplatform-side Stage 5 mid-execution commits: `1a552d9` (pause; Pre-Flight Step 1), `c20e298` (Phase E remediation), `ae75507` (Phase F remediation), close-unpause (LAST action; capture SHA via `git -C C:\Users\mrbla\devplatform log --oneline -1` post-step-(8)).

Tags created at Item 5.11 (n1(l) precondition guard PASSED; BlarAI on `main` post-step-(2) merge):
- BlarAI **`post-platform-extract`** (tag SHA: `67d0025`) → annotates `4122b92` (merge commit on main)
- devplatform **`platform-extracted`** (tag SHA: `896d591`) → annotates `ae75507` (Phase F commit; latest devplatform main tip pre-close-unpause)
- BlarAI **`pre-platform-extract`** (tag SHA: `ce2ec58`) → annotates Stage 0 baseline `d0dc1c7` — PRESERVED per RECOVERY.md asset coverage matrix; rollback parachute integrity verified at Pre-Flight Step 0 (5/5 PASS).

### 9. Anomalies bound (A20-A33)
- **A20** (carried from Guide-#8 handoff): wake_launcher auto-stash narrative correction (don't pop discipline; dn10 reinforcement)
- **A21**: Stage 5 init pointer `<v0_pickup_verification_block>` expected text doc-defect (BlarAI_HEAD + BlarAI_working_tree fields presumed Step 1 commits on both repos; canonical fleet-pause SOP commits only on devplatform; Operating Rule 5b(a) STATUS-staleness; bound to Ticket MM)
- **A22**: ext2 strict-count test design too narrow (`Count -eq 13` doesn't anticipate forensic XML residues; 6 EA-8-era forensic artifacts in `scheduled_tasks_export/` directory: 2 `_item47_phase*_results.xml` + 4 `_dbg_*` / `_item47_phase*_*.ps1` files; bound to Ticket MM scope)
- **A23**: BlarAI Vikunja zombie process discovery during Stage 5.1 (PID 11964 launched 2026-04-29T00:44Z = ~10h post-Stage-4-cutover from unknown launcher; Startup .lnk filename is `Vikunja (BlarAI).lnk` (NOT `Vikunja.lnk`) per Guide-#9 cross-verification; .lnk TargetPath verified correct pointing devplatform — Stage 4.9 rewrite SUCCEEDED; .lnk is NOT the zombie launch mechanism; investigation deferred to Ticket SS)
- **A24**: scheduled-tasks/ empty `logs/` residue after first Item 5.1 attempt (transient OS dir handle); resolved at retry per LA option (a)+ paste-relay #1 elevated `Remove-Item`; non-blocking
- **A25**: Phase E remediation (3 PS1 scripts; commit c20e298)
- **A26**: cadence_monitor BlarAI logs spanned 8+ days through Phase D soak (procedural lesson — soaks should audit log paths AS PART OF acceptance criteria; Phase D acceptance criteria did not include log-path verification, allowing Phase-C-BUG-1 to persist on cadence_monitor side until Stage 5.1 deletion exposed it)
- **A27**: minor reporting drifts during Stage 5 mid-execution (audit archive 1500 vs 1499 count discrepancy resolved as case-insensitive Get-ChildItem double-counting on `DOMAIN*.md` + `domain*.md`; .platform/active_tasks.yaml 65 vs 102 bytes resolved as line-ending normalization)
- **A28**: `.platform/sprints/_templates/` + `.platform/scheduled/wake_templates/` empty post-Item-5.3 (cosmetic; subdirs exist but contain no files — pre-move BlarAI/scheduled/wake_templates was a sparse mirror; the actual wake_template content is at devplatform/docs/scheduled/wake_templates/ per Stage 3.2.v2)
- **A29**: Phase F remediation Item-5.4-audit-discovered Phase-C-pattern resurfacing (Phase C be22a15 fixed only lines 69 + 809 of wake_launcher.ps1; 8 other dynamic-path drifts surfaced at Item 5.4 audit broader sweep per t11/dn35; 7 closed at Phase F commit ae75507; line 482 verified correct as-is)
- **A30**: Item 5.8.v2 pytest BENEFICIAL drift +20 (1001 passed / 2 skipped vs CLAUDE.md baseline 981/22; 20 env-dependent skips resolved due to live runtime availability; same 1003 collection total; 0 failures; not a regression)
- **A31**: LA boot test runtime isolation note (Phase D mid-soak BlarAI runtime launch + prompt response test confirmed services/policy_agent + services/assistant_orchestrator unaffected by dev-platform extraction; renumbered from A30 per LA decision when EA-9 A30 took the letter for pytest beneficial drift)
- **A32**: 11 Stage-4-cycle placeholder ticket bodies retired (2026-04-30, Guide-#10 + LA Phase 1 dispatch). Letters K, L, M, V, W, Y, Z, AA, BB, CC, EE (Vikunja IDs 284-288, 290-295) were enumerated as inheritance slots in the Stage 4 close backlog (4.13 handoff line 376; STATUS.md §6 line 387) but no granular binding context was preserved in committed audit-chain artifacts. Guide-#10 one-pass search across Stages 0-3 dispatch + handoff XMLs + STATUS.md returned zero recoverable scope. Retired via Defunct label (id 22, gray #9E9E9E) + complete_task per LA directive 2026-04-30. Both label-and-complete (not either-or): completion stats stay clean while the Defunct label provides a visible audit marker that no execution work was performed. Documentation-defect remediation, not hardening-optionality concession. Skip-the-cancelled-letter convention applies to any future backlog re-enumeration. Backlog count 36 → 25 active.
- **A33**: Vikunja MCP server `complete_task` data-loss bug discovered 2026-05-07T19:41Z mid-EA-10 Phase 1 (KK initial close attempt). POST body to `POST /tasks/{id}` contains only `{"done": True}`; Vikunja backend zeroes absent fields (description=`""`, priority=0) per Go zero-value defaults. Title preserved (server-side required-field validation); labels + comments preserved (separate join tables). Secondary path defect: hardcoded `\tasks\` (Python tab-escape) vs correct `/tasks/`. Both confirmed via Guide-#10 source inspection of `devplatform/tools/vikunja_mcp/server.py`. KK (id 301) initial close erased description + priority; restored at update_task call (full body + done=True). Phase 1 12 ticket closes (KK + 11 placeholders + OO) executed via Option B workaround per Guide-#10 disposition 2026-05-07: read task → preserve title/description/priority → `update_task(task_id, ..., done=True)`; `complete_task` NOT used post-bug-discovery. Proper MCP server fix bound to new Ticket WW (Vikunja id 318): PATCH semantics + path normalization + regression test for description+priority preservation across closure.

### 10. Stage 5 transitions to Stage 6 (Hardening)
**Stage 5 operationally CLOSED at 2026-04-30**. Platform separation execution complete. devplatform now sole authoritative platform layer; BlarAI reduced to product-only surface (USE-CASE-001 + USE-CASE-004 runtime + openvino_contrib_agent + BlarAI-internal docs/governance/ 13 docs).

**Stage 6 — Hardening** (LOW risk per Master Plan §6) is next. Could optionally go through the fleet now per Master Plan §4 (post-cutover the fleet runs cleanly from devplatform). Stage 6.7.5 hardening backlog (28 tickets) is the consolidated cleanup queue. Triple-subagent verification (S1/S2/S3) at Stage 5 close per d6/w14/ack11 will be spawned by Guide-#9 post-close-unpause.

Stage 5 close LAST action (per fleet-pause SOP §3 + dispatch): `state.resume_fleet` on devplatform/tools/autonomy_budget/state.json (commit on devplatform main; `chore(ops): unpause fleet -- Stage 5 cleanup done`).

### 11. Post-Stage-5-close evolution (chronological; verdict snapshot at 28 tickets preserved per no-amend doctrine)

State has evolved post-5.12-verdict-emission per LA-driven decisions. Evolution recorded here for audit-chain traceability without amending the verdict snapshot:

**E1 — Stage 5 close evidence pack** (BlarAI commit `e36e9f8`, 2026-04-30): 6 artifacts committed (5.12 close verdict + S1/S2/S3 subagent outputs + 5.13 boundary gate verdict + soak_log.txt 1275-line 45-cycle observation log).

**E2 — Stage 5→6 boundary gate APPROVED** (per `temp_for_responses/5.13-GUIDE_RESPONSE_INSTANCE_9_STAGE5_TO_STAGE6_BOUNDARY_GATE.xml`, 2026-04-30T17:42Z): 6/6 criteria PASS. LA explicitly REJECTED the Master Plan §6.7 24h soak as "over-engineering"; 45-min soak observation accepted as sufficient baseline (dn31 prohibition added).

**E3 — Ticket UU bound** (BlarAI commit `777e4a5`, 2026-04-30): post-verdict architectural discussion bound UU (Vikunja-project rationalization). Backlog 28 → 29.

**E4 — Ticket MM scope corrections inline** (BlarAI commit `9a23911`, 2026-04-30): Drift §1 (commit-stat numerics; this §8) + Drift §2 (inherited-list LL letter; this §7) resolved per Stage 5 close verdict drift_items.

**E5 — Stage-4-close enumeration gap recovery** (BlarAI commit `8f9220c`, 2026-04-30): tickets B/C/D/E/F/G surfaced via Vikunja-binding cross-verification ("I don't see tickets B, C, D, E, S and others"); silently dropped from Stage 4 close enumeration despite explicit binding at Stage 3 close + Stage 4 preflight; recovered to backlog with full origin-trail metadata. Backlog 29 → 35.

**E6 — Guide-#9 → Guide-#10 handoff brief** (BlarAI commit `fefb16a`, 2026-04-30): 5.14 handoff brief at `temp_for_responses/5.14-GUIDE_HANDOFF_INSTANCE_9_TO_10.xml` + GUIDE_HANDOFF_LATEST.xml updated. Decisions d28-d32 + prohibitions dn31-dn33 + watchpoints w23-w25 added.

**E7 — soak_monitor.ps1 migration** (devplatform commit `19bed62`, 2026-04-30): parameterized fleet observation tool migrated from BlarAI ad-hoc location to `devplatform/tools/fleet_observability/soak_monitor.ps1`; doubles as Stage 6.7.5 Ticket RR scaffold.

**E8 — Stage 5.3 partial reversal** (BlarAI commit `1dd5a4b` + devplatform commit `8b0ad16`, 2026-04-30): pre-Guide-#10-spawn spot-check of /sprint-discovery + /sprint-debrief + /sprint-kickoff revealed all 3 commands assume `docs/active_tasks.yaml` + `docs/sprints/...` paths uniformly, but Item 5.3 had moved files to `.platform/`; LA directed reversal ("an oversight on my part... they need to be in the docs folder"). Reverted: `.platform/active_tasks.yaml` → `docs/active_tasks.yaml`; `.platform/docs_sprints/` → `docs/sprints/` (175 file renames preserving git history); `.platform/scheduled/` removed (was empty placeholder; `docs/scheduled/` already tracked); wake_launcher.ps1 lines 344+492+833 reverted from `.platform\` → `docs\`. What stays at `.platform/`: audit_archive/ + vikunja_project_ids.yaml. Smoke test PASS: `load_roster()` works with restored path.

**E9 — Ticket VV bound** (Vikunja id 317, 2026-04-30): cross-repo path resolution audit + Stage 5.3 reversal cleanup. HIGH priority. Sub-items: (i) autonomy_budget DEFAULT_ROSTER_PATH cross-repo defect at `active_tasks.py:38` (resolves to non-existent `devplatform/docs/active_tasks.yaml` — pre-existing bug not introduced by reversal); (ii) docstring + README alignment audit; (iii) end-to-end smoke test of all 3 sprint commands. Backlog 35 → 36.

**E10 — Stage 6 Phase 2 (Items 6.4+6.5) complete** (devplatform commits `1e21bc5` (pause) + `20d8fc2` (6.4) + `71436e7` (unpause), BlarAI commit _(this commit; recover via `git log -1 --oneline -- docs/platform_separation/STATUS.md`)_, 2026-05-07): Item 6.4 — devplatform/pyproject.toml finalized: `authors` field added ({name="Blair", email="mr.blair.do@gmail.com"}). Item 6.5 — BlarAI/docs/ sweep: PASS (1 false positive `docs/_claude_projects_dirty.log` — gitignored post-commit ephemeral artifact, disposed by Guide-#10; no platform-doctrine files found). Hardening backlog: 38 total / 14 done / 24 open after Phase 2 tracking task close (was 37/13/24 at boot; +1 total / +1 done / open unchanged via Vikunja task #319). Phase 2 dispatch correction (no STATUS.md A-number per Guide-#10 disposition): Check 0b text incorrectly tested BlarAI for `platform-extracted` — that tag is on devplatform `ae75507`; waived as documentation-only defect, all 3 platform-extraction tags intact at documented SHAs.

**E11 — Stage 6 Phase 3 (Tickets A+X) complete** (devplatform commits `f50343a` (Phase 3 pause) + `dea5f3e` (TicketX) + Phase 3 unpause-commit immediately follows this STATUS.md commit per fleet-pause SOP §3, BlarAI commits `a00cf95` (TicketA) + _(this commit; recover via `git log -1 --oneline -- docs/platform_separation/STATUS.md`)_, 2026-05-07): **Ticket A** — Stage 3 EA-numbering posterity correction published at `docs/platform_separation/A_STAGE3_EA_NUMBERING_POSTERITY.md`; `g7-ea1_n*` → `g7-ea7_n*` cross-reference table covers 13 ack atoms (n1-n13) with ~130+ in-text occurrences across 4 frozen verdict files (3.0.v2, 3.1.v2, 3.2.v2, 3.10-CLOSE_VERIFIED); `INFRA_DELTA_v2.md` typo corrected at lines 121+125 (`.ps1` hyphen→underscore) + line 337 (wildcard `escalation-watchdog.*` split into explicit `escalation_watchdog.ps1` + `escalation-watchdog.xml` for precision); lines 134+257 preserved (line 134 is the genuinely-hyphenated `.xml` task-XML filename per verdict 3.1.v2 §(a); line 257 is informal bare reference where actual Task Scheduler entry is `Escalation Watchdog` with Title Case Spaces). Frozen verdict files NEVER edited per dn30. **Ticket X** — `devplatform/docs/governance/subagent_verification_protocol.md` published (A18 resolution; core rule + 12-row standard verification commands table by claim type for Guide cross-check passes; `GUIDE_HANDOFF_LATEST.xml` incorporation explicitly deferred to next Co-Lead Phase 3 Guide transition, NOT EA-12 scope). Hardening backlog: 39 total / 17 done / 22 open after Phase 3 tracking task (Vikunja id 323) close (was 38/14/24 at boot; net +1 total / +3 done / -2 open).

**E12 — Stage 6 Phase 4 (Tickets II+JJ) complete** (devplatform commits `049cc41` (Phase 4 pause) + `d478c05` (C1 — 5 PS1 scripts refactored on `feat/stage6-phase4-ps1-env-var-refactor`) + Phase 4 merge-to-main + Phase 4 unpause _(both follow this Phase 4 STATUS.md commit per dispatch ordering; recover via `git log --oneline main` on devplatform)_, BlarAI commit _(this commit; recover via `git log -1 --oneline -- docs/platform_separation/STATUS.md`)_, 2026-05-07): **Ticket II** (Vikunja id 299) — 5 PS1 fleet scripts (agents-cadence-monitor, escalation_watchdog, la_merge_approve, test_async_post_gate, wake_launcher) refactored from `.mcp.json` ConvertFrom-Json credential reads to direct `$env:VIKUNJA_URL/USER/PASS` pattern (Python parity per `vikunja_mcp/cli.py`); diff 5 files / +31 / −78. la_merge_approve.ps1:189 trigger path fixed (`$PSScriptRoot`-based, was `$RepoRoot` — trigger now writes to `devplatform/tools/scheduled-tasks/triggers/` where wake_launcher reads it; previously wrote to BlarAI side and was never seen). wake_launcher.ps1 `Test-WorkAvailable` `[string]$McpConfigPath = 'C:\Users\mrbla\BlarAI\.mcp.json'` parameter removed (sole call site at line 853 verified to not pass it). **Ticket JJ** (Vikunja id 300) — `BlarAI/.mcp.json` `VIKUNJA_PASS` reverted from literal (Phase C A16 emergency revert) back to `${env:VIKUNJA_PASS}` template; both `.mcp.json` files (BlarAI + devplatform) now consistent. Gitignored — no git commit; V3 (template present, env var set, file not staged) sole completion evidence. **V1 grep edge case (note for posterity)**: 3 incidental hits in wake_launcher.ps1 lines 641/643/646 — all in worktree-copy logic (Pattern B addendum, Bug #2 fix 2026-04-23) that propagates gitignored `.mcp.json` + `.env` from main into spawned Claude EA session worktree for MCP loader bootstrap; out of Ticket II credential-refactor scope (file copy, not credential read); V1 PASSES by intent. **Pre-flight 0c**: initial fail (VIKUNJA_URL + VIKUNJA_USER not in this Claude Code session's process env — User-scope additions post-dating session launch); LA authorized session-local injection from User scope; ALL SET on re-run; 0d login smoke PASS. **Fail-open/closed semantics post-refactor (CG8)**: wake_launcher.ps1 retains FAIL-OPEN on missing env vars (work-gate auth failure → fire Claude rather than silently block all work; matches pre-refactor `.mcp.json`-absent behaviour); other 4 scripts fail-closed — agents-cadence-monitor + escalation_watchdog exit 0 silent, la_merge_approve exit 2 with explicit fixup message, test_async_post_gate `throw` (test-script semantics). Hardening backlog: 40 total / 20 done / 20 open after Phase 4 tracking task close (was 39/17/22 at Phase 3 close; net +1 total via tracking task #324 / +3 done via II 299 + JJ 300 + tracking task close).

**E13 — Stage 6 Phase 5 (Ticket VV) complete** (devplatform commits `681a905` (Phase 5 pause) + `bebd6e2` (C1 — DEFAULT_ROSTER_PATH cross-repo fix + 3 docstring updates on `feat/stage6-phase5-cross-repo-path-fix`) + Phase 5 merge-to-main + Phase 5 unpause _(both follow this Phase 5 STATUS.md commit per dispatch ordering; recover via `git log --oneline main` on devplatform)_, BlarAI commit _(this commit; recover via `git log -1 --oneline -- docs/platform_separation/STATUS.md`)_, 2026-05-08): **Ticket VV** (Vikunja id 317) sub-item (i) — `DEFAULT_ROSTER_PATH` cross-repo defect fixed in `devplatform/tools/autonomy_budget/active_tasks.py`: now derives from `DEFAULT_BLARAI_ROOT` (imported from `tools._project_context`) instead of devplatform `REPO_ROOT`, resolving to `BlarAI/docs/active_tasks.yaml` (the authoritative roster location). `REPO_ROOT` and `DEFAULT_SCHEMA_PATH` retained unchanged — schema correctly lives in devplatform. Sub-item (ii): docstrings updated in `active_tasks.py` (line 7 module docstring), `proactive_colead.py` (~line 61 `roster_path` parameter docstring), `proactive_sdo.py` (~line 59 `roster_path` parameter docstring) — all now reference the cross-repo `BlarAI/docs/active_tasks.yaml` path explicitly. Sub-item (iii): smoke tests TEST 1–4 all PASS — TEST 1 (`load_roster()` without override returns valid roster; `DEFAULT_ROSTER_PATH` equals expected `C:\Users\mrbla\BlarAI\docs\active_tasks.yaml` and `.exists()`), TEST 2 (`proactive_colead` + `proactive_sdo` modules import cleanly + share fixed default), TEST 3 (sprint Phase 0 prerequisites all present: `BlarAI/docs/active_tasks.yaml` + `BlarAI/docs/sprints/ACTIVE_SPRINT.md` + `BlarAI/docs/sprints/_templates`), TEST 4 (`DEFAULT_SCHEMA_PATH` unchanged at devplatform side). Full `/sprint-kickoff` invocation explicitly OUT OF SCOPE per ack g10-ea14_n7 — interactive LA-only; flagged as "requires manual LA verification" in close report. **MCP-403-P5 incident**: Vikunja MCP server cached a stale `VIKUNJA_PASS` at session start (pre-rotation); MCP returned 403 on tool calls while direct REST login with current User-scope `VIKUNJA_PASS` (length 23) succeeded. LA authorized REST fallback for all 3 Phase 5 Vikunja writes (tracking task 325 create + Ticket VV 317 close + tracking task 325 close at PF1 PASS); A33 Option B logic preserved (get → update done=True with title/description/priority preserved → comment) just executed via `Invoke-RestMethod` instead of MCP. Byte-equivalent to MCP path; A5-precedent. Documented in close report narrative; not a formal fleet anomaly per LA disposition. **Backlog**: 41 total / 22 done / 19 open after Phase 5 tracking task close (was 40/20/20 at boot; net +1 total via tracking task #325 / +2 done via VV 317 + tracking task 325 / −1 open via VV).

**E14 — Stage 6 Phase 6 (Ticket WW) complete** (devplatform commits `763a983` (Phase 6 pause) + `ea2fbf5` (Phase 6 C1 — complete_task read-then-write fix + 4 regression tests on `feat/stage6-phase6-ww-complete-task-fix`) + Phase 6 merge-to-main + Phase 6 unpause _(both follow this Phase 6 STATUS.md commit per dispatch ordering; recover via `git log --oneline main` on devplatform)_, BlarAI commit _(this commit; recover via `git log -1 --oneline -- docs/platform_separation/STATUS.md`)_, 2026-05-08): **Ticket WW** (Vikunja id 318) — complete_task data-loss bug (A33) fixed in `devplatform/tools/vikunja_mcp/server.py` — changed from POST-only `{"done": True}` to read-then-write (GET title/description/priority → POST with all fields + done=True). Secondary defect (backslash path `\tasks\`): not found in current HEAD — no fix needed. 4 regression tests added in `test_server_ww.py` — all PASS (8/8 total including 4 pre-existing). After MCP server restart, `mcp__vikunja__complete_task` restored to safe operation; A33 Option B workaround deprecated. **MCP-403-P5**: MCP returned 403 (stale VIKUNJA_PASS in config files); REST API fallback used for all 3 Phase 6 Vikunja writes (tracking task 342 create + Ticket WW 318 close + tracking task 342 close at PF1 PASS); byte-equivalent to MCP path per A5-precedent. **Backlog**: 43 total / 24 done / 19 open after Phase 6 tracking task close (was 42/22/20 at boot; net +1 total via tracking task #342 / +2 done via WW 318 + tracking task 342 / −1 open via WW 318).

**E15 — Stage 6 Phase 7 (FINAL) complete; Stage 6.7.5 hardening DECLARED COMPLETE** (devplatform commits `77c99af` (Phase 7 pause) + `bdb7361` (Phase 7 C1 — Tickets G+I+FF close-out + PLATFORM_SEPARATION_HISTORY.md on `feat/stage6-phase7-close-out`) + Phase 7 merge-to-main + Phase 7 unpause _(both follow this Phase 7 STATUS.md commit per dispatch ordering; recover via `git log --oneline main` on devplatform)_, BlarAI commit _(this commit; recover via `git log -1 --oneline -- docs/platform_separation/STATUS.md`)_, 2026-05-08): **Ticket G (315)** — Check 0d independent XML scan: 6 scheduled-task XMLs invoke `python.exe`, all using absolute venv path `C:\Users\mrbla\devplatform\.venv\Scripts\python.exe`; 7 invoke `wscript.exe + powershell.exe` (Pattern 9.8 exempt); 0 RELATIVE_OR_UNKNOWN. No XML edits required. Doctrine documented at `devplatform/docs/governance/fleet-hygiene.md` §10.1 with verification one-liner and the Check 0d audit table as the baseline. **Ticket I (283)** — `devplatform/.gitignore` updated with `.mcp.json` entry in the "Secrets files" section (after `.env.local`). Both `.mcp.json` files (BlarAI + devplatform) confirmed template format `${env:VIKUNJA_PASS}` + gitignored in their respective repos. Final disposition documented at `fleet-hygiene.md` §10.2: PS1 fleet scripts read `$env:VIKUNJA_*` directly (Phase 4 Ticket II); MCP loaders resolve template at session start; literal credentials require rotation. **Ticket FF (296)** — Check 0e independent wrapper search: no wrapper script found anywhere in `devplatform` (excluding venv/__pycache__/.mypy_cache). `vikunja_mcp/` directory contains only cli.py, server.py, seed_data.py, README.md, __init__.py, tests/, bridge/. `tools/vikunja_mcp/README.md` updated with new "CLI Canonical Invocation (Option α)" section documenting `python -m tools.vikunja_mcp.cli <command>` as the supported pattern; n1(l) wrapper formally retired (never authored). **Ticket XX (328)** — `blarai_next_task_resolver.py` read in full: constructor (line 102) defaults `repo_root` to `_project_context.DEFAULT_BLARAI_ROOT` ✓; no module-level docstring references to `docs/active_tasks.yaml` ambiguously; `continuation_template` resolved against `self._repo_root` (line 155, anchored to BlarAI root via DEFAULT_BLARAI_ROOT default); no ambiguous "repo root" phrasing. Alignment confirmed; no file changes — XX absent from C1. **`devplatform/docs/PLATFORM_SEPARATION_HISTORY.md`** created (pointer doc for future-devplatform contributors): summary + 7-decision architectural-decision log (env-var credential pattern, cross-repo path constant, absolute python.exe paths, .mcp.json template + gitignored, direct module invocation, complete_task fix, wake_launcher fail-open) + Stage 6.7.5 phase table + related-repos table. **complete_task path**: Check 0f confirmed `RESTORED: True` (Phase 6 fix loaded after user restart of Claude Code); `mcp__vikunja__complete_task` used directly for all 4 ticket closes (G/I/FF/XX) and the Phase 7 tracking task close — A33 Option B workaround not invoked, MCP-403-P5 not encountered (Phase 7 pre-flight env was clean). **Stage 6.7.5 hardening DECLARED COMPLETE.** Remaining 15 open tickets in Vikunja Project 10 are NOT closed; they migrate to the Phase 5 post-operational backlog and will be addressed in future sprints (per dispatch ack g10-ea16_n7). **Backlog**: 44 total / 29 done / 15 open after Phase 7 tracking task close (was 43/24/19 at boot; net +1 total via tracking task #343 / +5 done via G 315 + I 283 + FF 296 + XX 328 + tracking task 343 / −4 open via G+I+FF+XX). **Observed pre-flight state** (non-blocking): two untracked `.flag` files at `tools/fleet_observability/` (`critical_pending.flag`, `vikunja_down.flag`) — runtime observability state from prior firings; not staged. Pre-existing minor doc drift in `tools/vikunja_mcp/README.md` Quick Start §2 (`cd C:\Users\mrbla\BlarAI` should be `cd C:\Users\mrbla\devplatform` post-Stage-4-cutover) — noted; deferred to Phase 5 post-operational backlog per Constraint C-SCOPE. **Anomalies bound this phase**: none new.

**E16 — Stage 6 FINAL — Platform Separation v2 COMPLETE** (devplatform commits `2be9a0b` (Phase 8 pause) + Phase 8 PLATFORM_SEPARATION_HISTORY.md pointer-update commit + Phase 8 unpause _(both follow this STATUS.md commit per dispatch ordering; recover via `git log --oneline main` on devplatform — unpause commit subject contains "Stage 6 FINAL complete; Platform Separation v2 COMPLETE")_, BlarAI commits _(this STATUS.md E16 commit + close-report commit + archive-move commit; recover via `git log --follow --oneline -- docs/archive/platform_separation/STATUS.md` for the E16 commit subject 'docs(stage6_final): Stage 6 FINAL -- Platform Separation v2 COMPLETE (E16)' and `git log --oneline -- docs/archive/platform_separation/` for the archive-move commit subject)_, 2026-05-08): **Item 6.7 (24h soak observation)**: PASS — empirical soak window 2026-04-28 (Stage 4 cutover, devplatform `df3d940`) → 2026-05-08 (this entry) = 10 days continuous fleet operation including 7 Stage 6.7.5 hardening phases (E8–E15). Check 0g metrics: 12 of 13 scheduled tasks at TaskPath '\BlarAI\' returned LastTaskResult=0 (1 documented exception: Gate Stale Cleaner returned exit code 1 on 2026-05-07 01:00:01 — non-fatal partial-error per `tools/gate_stale_cleaner/run_live.py:60-64` semantics, Vikunja was reachable but `report.errors` non-empty after sweep; within "up to 1 documented exception" allowance per dispatch §preflight 0g); Vikunja DB size 3,649,536 bytes at `C:/Users/mrbla/AppData/Local/Vikunja/vikunja.db` (dispatch §0g path `tools/vikunja/vikunja.db` was incorrect — actual location per `tools/vikunja/config.yml:14` is `%LOCALAPPDATA%\Vikunja\vikunja.db`; corrected at execution); bridge daemon ABSENT (non-blocker per dispatch — bridge is host-side infrastructure for Cowork/Codex sandboxes, Claude Code main session uses MCP directly; absence documented with rationale). No-unexpected-BlarAI-access architectural property already validated by Stage 6.7.5 Tickets II + JJ + VV (cross-repo path work; confirmed in E11–E13). **Item 6.9 (archive)**: `docs/platform_separation/` moved to `docs/archive/platform_separation/` via `git mv` (preserves file history through the rename — `git log --follow` on new paths returns pre-move history). All contents migrated including the 4 frozen Stage 3 verdict files (3.0.v2 / 3.1.v2 / 3.2.v2 / 3.10) at their post-archive paths under `docs/archive/platform_separation/temp_for_responses/`, EA-1..EA-17 dispatches and close reports, all Stage 0..6 procedural XMLs (`01_STAGE0_PREFLIGHT.xml..07_STAGE6_HARDENING.xml`), and platform-separation governance docs (`00_MASTER_PLAN.md`, `INFRA_DELTA_v2.md`, `RECOVERY.md`, `ROLLBACK_NOVICE_GUIDE.md`, `VERIFICATION_COMMANDS.md`, `AUDIT_RISK_REVIEW.md`, this STATUS.md). C-NOEDIT preserved: frozen verdict files moved as `R` rename entries only, never `M` modify (verifiable via `git show <archive-move-SHA> --stat | findstr 3.0.v2 3.1.v2 3.2.v2 3.10`). **Item 6.10 (final entry)**: this entry. Closing-line update (`E1-E15` → `E1-E16`) follows below. **Deferrals**: Items 6.1, 6.2, 6.3 (split CLAUDE.md / `.github/copilot-instructions.md` / AGENTS.md between BlarAI and devplatform doctrine) and 6.6 (commit doctrine splits) DEFERRED per v2 6.1.v2 original disposition ("SOP work has already been done; defer split until separate session") + LA 2026-05-08 confirmation. Future revival ticket (if LA later wants the splits) gets a fresh ack chain — no implicit reactivation. Item 6.8 (optional fleet hand-off kickoff ticket) RESOLVED IMPLICITLY: Stage 6.7.5 Phases 1–7 saw 16 EA-Code instances (EA-1..EA-16, plus this EA-17) actively maintain devplatform via 13 documented commits (devplatform `ae75507`, `763a983`, `ea2fbf5`, `bc0be3d`, `13145c3`, `681a905`, `bebd6e2`, `3802805`, `83cda41`, `77c99af`, `bdb7361`, `bc2ce64`, `34baf0f`, plus all earlier Phase 1–4 work) — the bootstrap-paradox exit was effectuated by routine practice; no separate kickoff ticket required. **Backlog**: 45 total / 30 done / 15 open after Phase 8 tracking task close (was 44/29/15 at boot; net +1 total via tracking task #344 / +1 done via tracking task close / 0 open change — the 15 deferred Stage 6.7.5 tickets in Vikunja Project 10 'DevPlatform-Meta' remain open per Constraint C-DEFER-PRESERVE: UU 316, GG 297, HH 298, LL 302, MM 303, PP 305, QQ 306, RR 307, SS 308, TT 309, B 310, C 311, D 312, E 313, F 314). **Stage 6 declared CLOSED. Platform Separation v2 procedure declared COMPLETE.** Post-archive paths: BlarAI-side history at `C:\Users\mrbla\BlarAI\docs\archive\platform_separation\` (this STATUS.md is included in that archive); platform-side breadcrumb at `C:\Users\mrbla\devplatform\docs\PLATFORM_SEPARATION_HISTORY.md` (created Phase 7 / E15, contains pointer + 7 architectural decisions; pointer line updated this phase to reference the new archive path). **Anomalies bound this phase**: none new. **Pre-flight observation** (non-blocking, carried over from E15): two untracked `.flag` files at `devplatform/tools/fleet_observability/` (`critical_pending.flag`, `vikunja_down.flag`) — runtime observability state from prior firings, not staged; deferred to post-operational backlog handling. **Stage 6 closure terminal-state marker**: no Phase 9 follows; the 15 open Stage 6.7.5 tickets become standard post-operational backlog beyond Stage 6 scope.

**Cumulative-ack chain at evolution snapshot**: 132 binding atoms (unchanged from Stage 5 close — no new acks emitted post-verdict per dn30 no-amend doctrine; evolution items E1-E16 are doctrine-internal state changes, not procedural execution gates).
