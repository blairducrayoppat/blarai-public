# BlarAI Doctrine-Surface Audit — staleness, archaeology, and tug-vectors
*Auditor: doctrine-surface-audit subagent · 2026-07-18 · all repos READ-ONLY (no repo writes performed)*

## Executive read
The retired worlds are **the sprint cadence (SDV / SCR / SWAGR + "Sprint N" kickoff/close), the Co-Lead-Architect / SDO / EA fleet, and the devplatform agent platform**. CLAUDE.md itself was successfully rewritten terse+current on 2026-07-13 and is ~95% live. **The tug comes almost entirely from the satellite surfaces CLAUDE.md still force-points sessions at** — chiefly `docs/sprints/ACTIVE_SPRINT.md` (force-read every session; frozen ~6 weeks and 2 whole sprints behind, entirely SDV/SCR/SWAGR-framed) and `docs/TEST_GOVERNANCE.md §1` (also force-read; "EA/SDO"-owned language + a self-forbidden 6-chapter baseline-history block). A second auto-loaded doctrine surface, `.github/copilot-instructions.md`, is worse still: it pins a test baseline off by 6,306 tests and describes the whole fleet in retired cf-program/SDO/EA terms. The root cause is structural: these docs named their maintenance **owner as a role that no longer exists** (Co-Lead Architect Phase 3; "the EA that changes test counts"), so when the role was retired the docs simply froze.

**Token estimates use bytes ÷ 4.** Forced-read set per CLAUDE.md `<session_start_protocol>` grounding item 4 = CLAUDE.md (auto) + ACTIVE_SPRINT.md + TEST_GOVERNANCE.md §1 → ~**18,000 tokens loaded at every interactive session start, a large fraction of it stale or archaeology**, before any task-specific read.

---

## 1. PER-FILE VERDICTS

### docs/sprints/ACTIVE_SPRINT.md — 246 lines · ~5,700 tok · **FORCE-READ EVERY SESSION** (grounding item 4 + live_state_pointers)
**~5% LIVE · ~25% ARCHAEOLOGY (Sprint 7–11 detail tables, legitimately historical) · ~70% STALE-WRONG** (asserts a project state that is two sprints and six weeks out of date, and a maintenance model that no longer exists). This is the single worst offender because it is both the most stale AND force-read every session.
Worst 3:
- **L3:** `Auto-maintained by Co-Lead Architect Phase 3 on every sprint transition. Do **not** hand-edit — Co-Lead overwrites on the next transition.` → The Co-Lead Architect role is retired; nothing overwrites this file. This sentence is *why* it froze — it tells every editor to keep hands off and wait for an agent that will never run.
- **L7 / L13:** `**Last refresh (2026-06-07)**: **Sprint 16 CLOSED** … No sprint currently active — the next kickoff (Sprint 17 …) is the LA's.` → Sprints **17 and 18 both subsequently ran and closed** (`docs/sprints/sprint_17/`, `docs/sprints/sprint_18/` with `sprint18-close-confirm.md` dated 2026-07-02..04). The file never advanced past Sprint 16.
- **L5 / L225:** `**Source of truth**: docs/active_tasks.yaml` … `Scheduled agents use docs/active_tasks.yaml as authoritative.` → `active_tasks.yaml` is legacy/stale; Vikunja is the task SSOT (INDEX.md L65 + L169 confirm). Also internally inconsistent: L215 says "Sprint 14 closed 2026-06-06" while L7 says Sprint 16 — the file contradicts itself.

### docs/TEST_GOVERNANCE.md — 398 lines · ~7,800 tok · **§1 FORCE-READ EVERY SESSION**
**~55% LIVE (§2.5 posture, §2.6 LOCALAPPDATA isolation, §2.7 coverage mandate, §4 markers, §5 gate order, §6 test-dev policy are all genuinely load-bearing) · ~30% ARCHAEOLOGY (the §1 baseline growth-log + §3 Sprint-8 named-scope table) · ~15% STALE-WRONG (retired-role ownership language, self-violated append rule).**
Worst 3:
- **L5:** `**Maintained by:** The EA that changes test counts MUST update this document.` (echoed L60 "Standard EA quality gate", L66 "SDO-generated EA prompts", L222, L320 "SDO Prompt Integration") → EA (Executing Agent) and SDO are retired roles; the doc's stated maintainer does not exist.
- **L26:** the giant single-paragraph baseline block ends with its own rule — `do NOT append a chapter per merge, the live count lives here + in the shipping ticket` — yet the same block **is** six nested "**Prior chapter —**" chapters deep (8490→8430→8373 in L26, then 3225→3222→3215→3175→2991→2565 in L32). It violates the exact rule it states. See Special Exhibit (a).
- **L13–18 / L196–204:** §3 "**Canonical Baseline**" table still presents `UNIT 755 / FOCUSED 791 / FULL 835` — self-admitted at L28–30 to be "Sprint-8-era … **stale**." A table titled "Canonical Baseline / Current Baseline" whose own footnote says it is stale is a live stale-wrong surface.

### CLAUDE.md — 297 lines · ~9,580 tok · auto-loaded every session
**~95% LIVE-load-bearing** (rewritten terse 2026-07-13; `<status_snapshot>` is fresh, dated today 2026-07-18, gate 8518). **~5% liability, not from its own content but from what it force-points at.** No SDV/SCR/SWAGR/Co-Lead/EA language survives in it — the rewrite worked. Its one structural fault: `<session_start_protocol>` grounding item 4 and `<live_state_pointers>` both send every session to `ACTIVE_SPRINT.md` as "the live sprint pointer," laundering the single most-stale file with CLAUDE.md's authority. The highest-leverage single fix in the whole audit is to change that one pointer. (`<maintenance>` L294 even lists "legacy role-name mappings and devplatform fleet-management doctrine" as *deliberately excluded* — CLAUDE.md knows the retired world is retired; its satellites did not get the memo.)

### docs/DECISION_REGISTER.md — 97 lines · ~20,350 tok · live SSOT (ADR/DEC index)
**~90% LIVE · ~10% ARCHAEOLOGY · ~0% STALE-WRONG. POSITIVE EXAMPLE.** Dense (81 KB) but the density is legitimate — it indexes DEC-01..10 + ADR-005..040, one paragraph per decision, and carries a NON-OPTIONAL "index in the same change" maintenance rule (L5) that has actually been honored (updates logged 2026-07-10, -15). Only archaeology: the cf-program cross-repo section (L58–69) and the devplatform companion-register pointer (L11) — legitimate cross-references, compressible to ~2 lines but not wrong. The DEC-01..10 evidence pointers all resolve to `P5_TASK4_PRODUCTION_CONFIG_FEASIBILITY.md` (historical), but the decisions are LOCKED/live, so that is correct provenance, not staleness.

### FIELD_NOTES.md — 270 lines · ~4,760 tok · grep-before-touch reference
**~98% LIVE · ~2% ARCHAEOLOGY · 0% STALE-WRONG. POSITIVE EXAMPLE.** Every note is a real mechanical gotcha tied to a permanent lesson number, newest at the bottom (dates run to 2026-07-17). This is what a healthy, owner-clear reference surface looks like: additive, dated, no retired-role framing. No slim needed.

### CLAUDE.md satellite — .github/copilot-instructions.md — 222 lines · ~5,730 tok · **AUTO-LOADED for Copilot/Codex/AGENTS.md sessions** *(discovered, not in the named list — surfaced because TEST_GOVERNANCE L223 makes it a mandatory sync target and it is badly out of sync)*
**~35% LIVE · ~10% ARCHAEOLOGY · ~55% STALE-WRONG.** This is a second always-on doctrine surface and it is more retired-world than any named file.
Worst 3:
- **L143:** `Test baseline: 2212 passed, 2 skipped, 103 deselected on the standing gate` → live is **8518 / 0 / 0** (CLAUDE.md status_snapshot). Off by **6,306 tests**. TEST_GOVERNANCE L223 states "`.github/copilot-instructions.md` baseline MUST stay in sync with this document … Stale baselines are a governance violation." This is that violation, uncaught.
- **L16 / L3 / L33 / L70:** `multi-chat workflow with the cf-program redesigned agent shape (post-cf-3): an Orchestrator that tracks roadmap …`; `SDO / EA Code / Configuration Agent → Orchestrator / specialist subagents`; legacy SDO role block; "Every new agent session — SDO or EA — must demonstrate comprehension." → the entire agent-shape section is the retired fleet.
- **L135 / L212:** `sprint_lifecycle_pointer → C:\Users\mrbla\devplatform\CLAUDE.md §Current-Active-Sprint`; `fleet_responsibilities … live in devplatform doctrine (post-cf-3 …)` → points sessions **into the being-sunset devplatform repo** for the sprint protocol and fleet roles.

### docs/IMPLEMENTATION_PLAN.md — 1708 lines · ~26,370 tok · listed in CLAUDE.md live_state_pointers
**~5% LIVE · ~95% ARCHAEOLOGY · low STALE-WRONG.** Content is Phases 1–4 completed-step logs (P1.0–P1.14 "COMPLETE"), Phase-5 Task-4.x feasibility snapshots, all closed. Structurally an execution history, not a plan. Presented as a live pointer but almost nothing is forward-looking. Not aggressively *wrong* (it's honest history), but it is 26K tokens of "done" wearing a "live plan" label, with SDO/EA references embedded in the entries (L252/262/365/427…).

### Use Cases_FINAL.md — 610 lines · ~45,600 tok · product-vision SSOT
**~90% LIVE (canonical) · ~10% possibly datable, not audited line-by-line (structure-skim only).** The 7-UC vision; referenced "to confirm what a UC scopes," **not** force-read each session. Largest single file at ~45K tokens — a "read the relevant UC section, never the whole file" caution is warranted, but this is reference not doctrine and carries no retired-fleet framing. Low tug-vector.

### docs/governance/README.md — 350 lines · ~4,500 tok · governance landing page
**~60% LIVE (the domain-doc inventory: pgov-validation, ipc-protocol, gpu-runtime, rule-engine … are real runtime-governance docs) · ~15% ARCHAEOLOGY · ~25% STALE-WRONG framing.**
Worst 3:
- **L37:** `**Future agent** — Configuration Agent, Sprint Auditor, EA Code, SDO, Co-Lead Architect, or a successor model resuming …` → names **five retired fleet roles** as the live audience for the whole directory.
- **L42:** `before touching any fleet-shared file (tools/scheduled-tasks/wake_launcher.ps1 … the EA queue directories, the active roster)` → retired fleet infrastructure presented as current.
- **L264–277 / L306–310:** `GOV-MIGRATE — docs/TEST_GOVERNANCE.md → docs/governance/test.md … blocked on Sprint 8 closure (Vikunja #82)` → Sprint 8 closed **2026-04-23** (~3 months ago per ACTIVE_SPRINT L44); the migration's stated blocker is long gone and the migration was abandoned — a live "pending" note for dead work.

### docs/governance/handoff-brief-template.md — ~250 lines · ~2,500 tok · **POSITIVE CONTROL**
**~100% LIVE · 0% stale.** Dated 2026-07-17; references #855, the machine-checked `anchors` block, `scripts/verify_handoff_brief.py`, lesson 14, the current standing-ops surface. This is proof the project *can* keep a doctrine doc fresh — it has a clear current owner and a verifier gate. The contrast with its sibling `runbooks/active_state_refresh.md` (below) is the whole lesson.

### docs/MEMORY.md (auto-memory index) — auto-loaded every session
**~90% LIVE · ~10% retired-era entries** that load their one-line hooks into every session. Retired-world entries: `feedback_mature_reframing_needs_sdv_amendment` (SDV), `feedback_manual_auditor_invocation_paused_fleet` (Auditor + SDV wake template), `feedback_ea_numbering_global` (EA numbering), `project_cf_program_role_naming` / `project_anthropic_primitive_cycle` / `project_cf_1_closed` / `project_cf_1_5_closed` (cf-program), `feedback_calibrate_time_estimates_against_actuals` ("cf sprints run ~1-2 days"). `reference_decision_registers` (devplatform DEC-11..19) is borderline — a still-valid cross-repo pointer.

---

## 2. TUG-VECTOR REGISTER (consolidated category-(b): live surfaces presenting a retired world as current)
Grep basis: `SWAGR|SDV|SCR|Co-Lead|EA-[0-9]|active_tasks.yaml|ea_queue|SDO` = 12,838 hits / 607 files; `devplatform` = 4,228 / 184. **The overwhelming majority are correctly archived** (`docs/archive/platform_separation/`, `docs/ledger/`, `docs/sprints/sprint_N/`, `docs/reports/`, `docs/scheduled/ea_queue/archive/`) — those are category (a), fine. The category-(b) live-doctrine hits pulling today's sessions:

| # | Surface | Line(s) | Retired world | Quote (trimmed) | Force-read? |
|---|---------|---------|---------------|-----------------|-------------|
| 1 | sprints/ACTIVE_SPRINT.md | L3 | Co-Lead fleet | "Auto-maintained by Co-Lead Architect Phase 3 on every sprint transition" | **YES (every session)** |
| 2 | sprints/ACTIVE_SPRINT.md | L7,L13 | Sprint cadence | "Sprint 16 CLOSED … the next kickoff (Sprint 17…) is the LA's" | **YES** |
| 3 | sprints/ACTIVE_SPRINT.md | L5,L225 | active_tasks.yaml SSOT | "Source of truth: docs/active_tasks.yaml" | **YES** |
| 4 | sprints/ACTIVE_SPRINT.md | L21-45,L233 | SDV/SCR/SWAGR | whole artifact-tables + "Writer: Co-Lead Phase 3 Step 0" | **YES** |
| 5 | TEST_GOVERNANCE.md | L5 | EA fleet | "Maintained by: The EA that changes test counts MUST update this document" | **YES (§1)** |
| 6 | TEST_GOVERNANCE.md | L66,L320-323 | SDO/EA prompts | "Default scope for SDO-generated EA prompts"; "SDO Prompt Integration" | **YES (§1 adjacent)** |
| 7 | .github/copilot-instructions.md | L143 | Sprint-16 baseline | "Test baseline: 2212 passed" (live 8518; sync-rule violation) | **YES (Copilot/Codex)** |
| 8 | .github/copilot-instructions.md | L3,L16,L33,L70 | cf/SDO/EA fleet | "cf-program redesigned agent shape (post-cf-3)… SDO or EA" | **YES** |
| 9 | .github/copilot-instructions.md | L135,L212 | devplatform | "→ devplatform\CLAUDE.md §Current-Active-Sprint" | **YES** |
| 10 | governance/README.md | L37,L42 | 5 fleet roles | "Configuration Agent, Sprint Auditor, EA Code, SDO, Co-Lead Architect" | discoverable |
| 11 | governance/README.md | L264-277 | dead Sprint-8 migration | "GOV-MIGRATE … blocked on Sprint 8 closure" | discoverable |
| 12 | INDEX.md | L15-17,L28 | renamed section | "single source of truth … is CLAUDE.md (§ Active State)" (no longer exists) | discoverable |
| 13 | INDEX.md | L78,L86,L87 | SDV/SCR/SWAGR + EA queue | "Per-sprint strategic docs (SDV / SCR / SWAGR) … ACTIVE_SPRINT.md is the live sprint pointer" | discoverable |
| 14 | INDEX.md | L176-180 | self-contradiction | "**There is no STYLE.md**" — but STYLE.md exists (19 KB, 2026-07-16) | discoverable |
| 15 | runbooks/active_state_refresh.md | L5 | Co-Lead/SCR cadence | "Owner cadence: Co-Lead Architect at Sprint Kickoff Phase 3 … AND Sprint Close (SCR-authoring)" | discoverable |
| 16 | runbooks/AUTONOMOUS_FLEET_OPERATIONS.md | whole | Domain-8 devplatform fleet | "Register per-role wake-up scheduled tasks" (DOMAIN8_DEC11 budget) | discoverable |
| 17 | docs/claude_projects/ (6 files) | whole dir | Co-Lead/SDO/EA Projects | "the four Claude Chat Projects … Co-Lead Architect / SDO / EA Prompt Library"; gate-ladder EA→SDO→Co-Lead→Human | discoverable |
| 18 | docs/claude_cowork/01_EA_COWORK_INSTRUCTIONS.md | whole | EA cowork | retired EA-cowork instruction set | discoverable |
| 19 | MEMORY.md | 5-7 entries | SDV/EA/Auditor/cf | "Mature reframings need SDV amendment first"; "EA numbering is global"; cf-program entries | **YES (auto-memory)** |

**Count of distinct category-(b) live tug-vector passages/surfaces: 19** (4 of them force-read every interactive session; 3 more auto-load for Copilot/Codex; the auto-memory index adds a 4th force-read surface). The `claude_projects/` + `claude_cowork/` + fleet-runbook surfaces (10, 15–18) are **latent** — not force-loaded, but 100%-retired instruction manuals that would badly mislead any session that opens them (reachable via INDEX.md's live navigation table, which lists them without a "retired" flag).

---

## 3. SPECIAL EXHIBITS

**(a) TEST_GOVERNANCE §1's giant baseline block vs its own rule.**
Line 26 is ONE paragraph of ~3,500 chars (~**875 tokens**); with the L28–49 continuation and the L32 chapter-chain (~4,500 chars, ~**1,100 tokens**) the §1 baseline-history prose totals **~2,000 tokens** — and it is force-read every session. It nests **six** "Prior chapter —" blocks (day-session 8490 ⇽ overnight 8430 ⇽ 8373 in L26; then 3225 ⇽ 3222 ⇽ 3215 ⇽ 3175 ⇽ 2991 ⇽ 2565 in L32), each with SHAs and per-merge deltas. The block's own closing clause: *"the dated chapters below are the historical growth log — do NOT append a chapter per merge, the live count lives here + in the shipping ticket."* The doc states the rule and breaks it in the same breath. ~1,800 of those ~2,000 tokens are pure per-merge archaeology that belongs in the ledger.

**(b) ACTIVE_SPRINT.md staleness — fraction of top-block claims false today.**
Of the ~10 load-bearing assertions in the active block (L1–L31): FALSE = "Sprint 16 CLOSED … no sprint currently active [because 16 just closed]" (17+18 have since closed); "next kickoff is Sprint 17" (17 done); "Auto-maintained by Co-Lead Architect … overwrites on next transition" (role retired, never overwrites); "Source of truth: active_tasks.yaml" (Vikunja is SSOT); the entire "Sprint 15 detail" active block (L15–31, a closed sprint held as "active"); the L215 "Sprint 14 closed … next kickoff is the LA's" (contradicts L7). TRUE = the historic-sprint table for 7–14 is accurate history; "no sprint is currently active" is *accidentally* true (continuous ticket flow replaced sprints) but for the wrong reason. **≈ 8 of 10 active-block claims are false or misleading — ~80%.**

**(c) status_snapshot drift vs TEST_GOVERNANCE live figure — the briefing's premise is now inverted; verify on disk (done).**
The brief said "CLAUDE.md pins 8430 while TEST_GOVERNANCE says 8490." **On disk today that is stale in the opposite direction:** CLAUDE.md `<status_snapshot as_of="2026-07-18">` now reads **8518 / 0 / 0 / 125** (refreshed today with #107 + #853); TEST_GOVERNANCE §1 still reads **8490** (2026-07-17). So CLAUDE.md is the *fresher* surface by +28 tests / one day, and TEST_GOVERNANCE is the lagging one. Third surface: copilot-instructions.md L143 = **2212** (Sprint-16 era, −6,306). **Three doctrine surfaces, three different "current" gate counts (8518 / 8490 / 2212).** The drift is real; its direction just moved since the brief was written — exactly why the brief said "verify on disk, don't trust me." No single surface is authoritative-by-enforcement; CLAUDE.md's own `<live_state_pointers>` correctly says "never trust pinned counts … read these instead," which is the right instinct but is undercut by three files pinning three counts.

**(d) MEMORY.md index entries referencing retired eras** (load every session):
`feedback_mature_reframing_needs_sdv_amendment` · `feedback_manual_auditor_invocation_paused_fleet` · `feedback_ea_numbering_global` · `project_cf_program_role_naming` · `project_anthropic_primitive_cycle` · `project_cf_1_closed` · `project_cf_1_5_closed` · `feedback_calibrate_time_estimates_against_actuals`. Borderline (keep): `reference_decision_registers` (valid cross-repo pointer).

---

## 4. SLIM TARGETS (archive everything, delete nothing)

| File | Now | Healthy version contains | Target | Archive removed content to |
|------|-----|--------------------------|--------|----------------------------|
| **sprints/ACTIVE_SPRINT.md** | 246 ln / 5.7K tok / force-read | A ~20-line pointer: "Sprint/SDV/SCR/SWAGR cadence RETIRED (see DECISION_REGISTER); current world = continuous Vikunja ticket flow + worktree builders + headless dispatch. Historic sprints 7–18 → docs/sprints/sprint_N/." **Better still: also drop it from CLAUDE.md session_start grounding item 4.** | **~20 ln / ~0.5K tok** | `docs/sprints/_archive/ACTIVE_SPRINT_historic_through_sprint18.md` (the current body verbatim) |
| **TEST_GOVERNANCE.md** | 398 ln / 7.8K tok / §1 force-read | §1 scope table (current figure only + "read CLAUDE.md status_snapshot + shipping ticket"), §2.5/2.6/2.7 policy, §4/§5/§6, §7. Replace "EA/SDO" ownership language with "the session that changes test counts." Mark §3 Sprint-8 table `ARCHIVED`. | **~200 ln / ~4K tok** | `docs/ledger/test_baseline_history.md` (the L26/L32 growth-log chapters) |
| **.github/copilot-instructions.md** | 222 ln / 5.7K tok / auto-loaded | Rewrite to mirror CLAUDE.md's current world (worktree builders + headless dispatch; NO SDO/EA/Co-Lead/cf-shape); baseline = a pointer to CLAUDE.md status_snapshot, never a pinned integer; drop the devplatform sprint pointer. | **~120 ln / ~3K tok** | git history (it's a rewrite); no archive file needed |
| **IMPLEMENTATION_PLAN.md** | 1708 ln / 26.4K tok / live-pointer | A thin "current priorities → Vikunja" head + Phase-2 hardware gates if still cited. Drop from live_state_pointers or relabel "historical execution log." | **~60 ln / ~1K tok** | `docs/archive/2026/implementation_plan_phases1-4_task4x.md` |
| **governance/README.md** | 350 ln / 4.5K tok | Keep the domain-doc inventory + matrix (live). Rewrite the audience list to current roles (session / subagent / headless dispatch / operator / auditor). Delete the dead GOV-MIGRATE + Sprint-8-blocker notes. | **~260 ln / ~3.4K tok** | fold GOV-MIGRATE status into the ticket; no doc archive |
| **INDEX.md** | ~200 ln / 2.4K tok | In-place fix ~5 lines: "§ Active State" → "<status_snapshot>"; remove "There is no STYLE.md"; flag `claude_projects/`, `claude_cowork/`, `runbooks/AUTONOMOUS_FLEET_OPERATIONS.md`, `active_state_refresh.md` as **RETIRED-WORLD** in the subdir map. | ~200 ln (edits, not slim) | n/a |
| **claude_projects/ + claude_cowork/ (7 files)** | retired manuals | — (nothing live) | move whole dirs | `docs/archive/2026/retired_fleet_instructions/` (+ leave a 2-line stub README: "retired 2026-07; see CLAUDE.md") |
| **runbooks/AUTONOMOUS_FLEET_OPERATIONS.md, active_state_refresh.md** | Domain-8 / Co-Lead cadence | — | move | `docs/archive/2026/retired_fleet_runbooks/` |
| MEMORY.md retired entries | 5-7 files | delete the files + their index lines (memory doctrine allows deleting wrong memories) | — | delete per memory SOP (git history retains) |

**Biggest single slim win: IMPLEMENTATION_PLAN.md (~26.4K → ~1K tokens, −25K).** **Biggest *tug* win: ACTIVE_SPRINT.md** — smaller token count but it is force-read every session and ~80% false, so retiring it removes the most-cited pull toward the old world.

---

## 5. STRUCTURAL-CONTROL IDEAS (one-time cleanup will re-rot without these — it already did once)
The 2026-07-13 CLAUDE.md rewrite went terse+current, yet the satellites kept growing/aging. Why it re-rotted: (i) **no size/freshness budget** on any satellite; (ii) the satellites' **stated owner was a retired role** ("Co-Lead Phase 3", "the EA that changes counts"), so nobody maintained them; (iii) the one sync rule that existed (copilot baseline, TEST_GOV L223) was **documented but never gate-enforced.** Controls, mapped to the project's own doctrine ("THIRD instance ships a structural control"; deny-by-default gate tests like `test_no_new_raw_spawn_sites.py`):

1. **Re-own every force-read surface in current-world terms.** Rule: *a doctrine doc whose stated maintenance owner is a retired role is by definition stale.* Rewrite each `Maintained by:` / `Owner cadence:` / `Auto-maintained by` line to a role that exists today ("the merging session", "the monthly-retrospective session"). Highest-leverage, cheapest, kills the freeze mechanism at its root.

2. **A doctrine-freshness gate test** (add to the standing gate — the project already fails loud on gate tests): (a) FAIL if CLAUDE.md `<status_snapshot>` gate count ≠ TEST_GOVERNANCE §1 live figure ≠ copilot-instructions baseline (enforces the L223 sync rule that today is honored in the breach, off by 6,306); (b) FAIL if `ACTIVE_SPRINT.md` "Last refresh" date is >14 days older than `git log -1` on `main` (a frozen force-read pointer trips the gate); (c) enforce a per-file **line budget** on the force-read set (ACTIVE_SPRINT ≤ 30, TEST_GOV ≤ 220) — exceed it, fail.

3. **A retired-lexicon deny-scanner** over the force-read/auto-loaded set only (CLAUDE.md grounding list + copilot-instructions + MEMORY.md), same shape as the AST spawn-scanner: grep for `SWAGR|SDV|SCR\b|Co-Lead|\bSDO\b|EA-Code|§ Active State|Sprint 1[0-9]` and FAIL LOUD, with a small documented allowlist (e.g. an ADR *citing* the retired cadence historically). This is the deny-by-default control that structurally prevents re-metastasis into the always-on surfaces, while leaving the archive untouched.

4. **Prune the mandatory grounding list itself** (CLAUDE.md `<session_start_protocol>` item 4 + `<live_state_pointers>`). The cheapest permanent control is to *stop force-loading a surface that no longer earns it*: drop `ACTIVE_SPRINT.md` and `IMPLEMENTATION_PLAN.md` from the pointers, or replace ACTIVE_SPRINT with a one-line "no sprint cadence; Vikunja is the queue." A pointer that survives its target's retirement is the defect.

5. **Assign the sweep to an existing cadence, single-owner.** CLAUDE.md already mandates a **monthly retrospective** — bundle a "doctrine-freshness sweep" into it (run controls 2–3, reconcile the three gate counts, re-date ACTIVE_SPRINT or confirm it's the thin pointer). No new ritual; one owner; it rides the cadence that already exists, matching the project's "durability requires distribution" rule.

*(Governance note for whoever executes: retiring ACTIVE_SPRINT/IMPLEMENTATION_PLAN from the grounding list is a change to CLAUDE.md doctrine → per CLAUDE.md `<maintenance>`, that is a feature-branch + journal-entry + DECISION_REGISTER-row ship, and the "sprint cadence retired" fact should land as a DEC/ADR row so future sessions see it as a decision, not a mystery.)*
