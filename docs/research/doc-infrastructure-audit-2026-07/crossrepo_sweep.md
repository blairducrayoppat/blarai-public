# Cross-Repo + Memory + Worktree Sweep

Read-only inventory. Nothing was created, staged, committed, moved, or removed. Git limited to
`worktree list` / `branch --show-current` / `branch --merged` / `log` / `status`.
Date: 2026-07-18.

---

## 1. AGENTIC-SETUP

### 1a. The seven LESSONS-LEARNED.md copies — duplication mystery SOLVED

**Not forks, not accidental duplication — they are git-worktree working-tree copies of ONE tracked
file.** `docs/LESSONS-LEARNED.md` is a normal tracked file in `agentic-setup`. Every git worktree
checks out the full tree, so each worktree carries its own copy of that file, frozen at the point its
branch last touched it. The size spread is just "how far behind main each branch is."

| Copy | Size | Branch | Merged into main? |
|---|---|---|---|
| `docs/LESSONS-LEARNED.md` (main checkout) | **147 KB** | main | — **CANONICAL** |
| `.worktrees/m2-web-headless-capture/…` | 146 KB | feat/m2-web-headless-capture | MERGED (stale) |
| `.worktrees/ram-guard/…` | 139 KB | fix/714-ram-aware-concurrency | MERGED (stale) |
| `.worktrees/uc010-w4/…` | 139 KB | feat/uc010-dispatch-asset-w4 | MERGED (stale) |
| `.worktrees/670-coder-output-reliability/…` | 136 KB | feat/670-coder-output-reliability | MERGED (stale) |
| `.worktrees/676-core-shell/…` | 93 KB | feat/676-core-shell | MERGED (stale) |
| `.worktrees/675-build-signal/…` | 87 KB | feat/675-build-signal | MERGED (stale) |

**Canonical = `C:/Users/mrbla/agentic-setup/docs/LESSONS-LEARNED.md` (main, 147 KB, newest).** The 6
smaller copies are stale worktree checkouts. **All 6 of those worktree branches are already MERGED into
agentic-setup/main**, so all 6 worktrees are cleanup candidates — removing them deletes all 6 duplicate
copies at once. (Two more sibling worktree dirs exist: `agentic-setup-wt-694` = MERGED-stale;
`agentic-setup-wt-746` = UNMERGED-active. So **7 of 8 agentic-setup worktrees are merged-stale.**)

**Canonical structure / overlap-in-kind with BlarAI's LESSONS.md:** the canonical is a curated
"Change Log & Lessons" for the **30B coder** (OpenCode + OVMS + Qwen3-Coder-30B-A3B INT4), ~39 section
headers, tagged ✅/❌/⊘/🔬 with explicit "→ BlarAI" reuse notes. Its stated purpose is to *carry lessons
to BlarAI*. BlarAI's own `LESSONS.md` is 325 KB / ~284 numbered lessons (different, larger, whole-system
scope). They **overlap in KIND** (both are local-quantized-model-on-Lunar-Lake maturation lesson logs)
but **not in content** (coder-fleet lessons vs BlarAI-system lessons) — this is a deliberate
transfer relationship, not accidental duplication. **Do NOT merge them** (different subjects/repos).

### 1b. The brief (`docs/blarai-headless-coding-agent-brief.md`, 51 KB / ~12.7K tokens) — PREMISE CORRECTION

**The mission's premise ("loads PER-DISPATCH into every coder agent") is not supported by what is on
disk.** The brief is a one-time **build spec** — audience line: *"the Claude agent implementing the
headless-coding feature inside BlarAI."* Grep for the filename across agentic-setup (excluding
worktrees) finds it referenced by **4 documents only** — `BLUEPRINT.md`, `blarai-handoff-CLAUDE.md`
(*"This is the spec"*), `blarai-builder-brief-decomposition-and-swapback.md`, and itself. **No fleet
script, runner, or dispatch config injects it.** The actual per-dispatch coder context is
`~/.config/opencode/AGENTS.md` + `configs/opencode.json` + `configs/agents/*.md` — not this brief.

So the ~12.7K tokens are NOT hitting every coder. If a coder is being bloated, the surface to audit is
**AGENTS.md**, not this file. That said, the brief IS internally bloated *for its actual purpose* (a
build spec), and slimming is still worthwhile doc hygiene.

**Content classification (357 lines):**
- **~55% one-time build design (needed only while building the dispatch feature):** §1 mission,
  §4 Option-A swap state machine, §6 "what to discover inside BlarAI," §7.4 decomposer risk, §9
  milestone plan. A finished/parked feature does not re-read this every session.
- **~30% stable reusable doctrine:** §2 non-negotiables, §3 fleet interface (the API), §5 OpenCode
  mechanics, §7.1–7.3 sizing + pre-validate-the-ruler, §8 DO-NOT list. Restated ~3× (§2 ≈ §4.3 ≈ §8).
- **~15% now-STALE / resolved:** §10 dated running-log lessons (5 entries — belong in
  `LESSONS-LEARNED.md`, which already exists), plus [VERIFY]/[DISCOVER] landmines that §10's
  2026-07-05 entry marks CLOSED (openvino #11978 / #33896) but are still written as open in §6.

**Slim target (~120–150 lines / ~18 KB):** keep §1 (1 para) + §3 (interface) + condensed §4.1 handshake
+ §7.2/7.3 (the load-bearing decomposition doctrine) + ONE merged DO-NOT list (fold §2+§4.3+§8). Move
§10 dated lessons into `LESSONS-LEARNED.md`; collapse resolved [VERIFY] items to one line each.

### 1c. Runner-start vs per-dispatch load boundary (what already loads when)

From memory `project_fleet_code_load_boundaries` + the scripts inventory (95 `.ps1` in `scripts/`):
- **PER-DISPATCH (read fresh each task — edits leak into a running pass):** `fleet-lib.ps1`,
  `new-agent-task.ps1`, `verify-project.ps1`, the review agent def, and the coder's `AGENTS.md` /
  `opencode.json`.
- **RUNNER-START (loaded once — mid-pass merge affects next launch only):** BlarAI's
  `tools/dispatch_harness/*` (runner/monitor).
- **The brief loads NEITHER automatically** — on-demand design spec read by a feature-building session.

---

## 2. WORKTREE INVENTORY (BlarAI)

14 registered worktrees (13 `agent-<hash>` under `.claude/worktrees/` = Claude-harness isolation dirs;
1 manual `.worktrees/790-layout-cycle-owner`). **All 14 are DIRTY=0 — no uncommitted work at risk
anywhere.** Merge-state via `git branch --merged main` + main log cross-check.

| Worktree dir | Branch | Last commit | Dirty | Disk | Verdict |
|---|---|---|---|---|---|
| .claude/worktrees/agent-a03c43a2… | feat/774-st2-procspawn-migration | 2026-07-17 | 0 | 68 MB | **ACTIVE** (unmerged, recent) |
| .claude/worktrees/agent-a1be72ed… | feat/927-percard-run-budget | 2026-07-17 | 0 | 64 MB | **ACTIVE** (unmerged; LA-queue disposition pending) |
| .claude/worktrees/agent-a21973f0… | feat/23-weight-integrity-doc | 2026-07-15 | 0 | 58 MB | **MERGED-STALE** |
| .claude/worktrees/agent-a5ba228f… | fix/727-websearch-json-parse-guard | 2026-07-17 | 0 | 64 MB | **MERGED-STALE** |
| .claude/worktrees/agent-a8afd2ab… | feat/774-spawn-doctrine-gate | 2026-07-17 | 0 | 61 MB | **MERGED-STALE** |
| .claude/worktrees/agent-aaaffaa4… | feat/848-sg-boundary | 2026-07-12 | 0 | 61 MB | **MERGED-STALE** |
| .claude/worktrees/agent-ab5f02eb… | feat/765-oracle-quality-offline | 2026-07-17 | 0 | 67 MB | **MERGED-STALE** |
| .claude/worktrees/agent-abad60cb… | feat/843-c1-read-surface | 2026-07-12 | 0 | 69 MB | **ACTIVE?** unmerged + aging; a `feat/843-c1-reconcile` IS merged — possibly superseded, verify |
| .claude/worktrees/agent-abe4667e… | feat/763-oracle-to-coder | 2026-07-12 | 0 | 59 MB | **HELD** (deliberately alive — lands 2026-07-21 per snapshot; do NOT clean) |
| .claude/worktrees/agent-ac3afe20… | fix/895-token-count-reencode-guard | 2026-07-15 | 0 | 66 MB | **MERGED-STALE** |
| .claude/worktrees/agent-aeafbd9e… | feat/929-handoff-brief-verifier | 2026-07-17 | 0 | 61 MB | **MERGED-STALE** |
| .claude/worktrees/agent-af25948f… | feat/931-eval-model-dir-override | 2026-07-17 | 0 | 66 MB | **MERGED-STALE** |
| .claude/worktrees/agent-afee9dbd… | feat/longctx-vlm-instrument | 2026-07-17 | 0 | 67 MB | **MERGED-STALE** |
| .worktrees/790-layout-cycle-owner | feat/790-layout-cycle-owner | 2026-07-12 | 0 | 66 MB | **MERGED-STALE** |

**Disk math:**
- Total worktree footprint ≈ **897 MB** (`du`: 824 MB `.claude/worktrees` + 66 MB `.worktrees`).
- **10 MERGED-STALE worktrees = ~637 MB reclaimable** (clean, branch fully in main).
- 4 remain (260 MB): 2 genuinely active (#774-st2, #927), 1 to verify (#843-c1-read-surface may be
  superseded by the merged c1-reconcile), 1 deliberately HELD (#763 — leave it).
- BUILD_JOURNAL.md is **2.21 MiB** each; 14 copies = **30.9 MB**, of which **22.1 MB** sits in the 10
  stale worktrees. (The full-checkout number above is the real reclaim; BUILD_JOURNAL is just the
  single biggest file inside each.)

**Caveat:** cleanup is the main agent's / LA's call under "remove worktrees on REPORT, not commit."
Merged+clean is the strong safe signal; I did not (and cannot) confirm each was "reported." `agent-*`
dirs are harness-created — removal likely goes through the harness, not manual `git worktree remove`.
I changed nothing.

---

## 3. MEMORY DISPOSITIONS

**134 `.md` total = 133 memory files + MEMORY.md index (373 KB).** MEMORY.md index is **stale: 13
files are orphaned** (present on disk, not linked in the index) — see 3d.

### 3a. RETIRED-ERA candidates (cf-program sprint cadence / SDV / EA / Auditor fleet — devplatform-based, sunsetting)
| File | Disposition | Reason |
|---|---|---|
| project_cf_program_role_naming.md | **RETIRE→ARCHIVE** | Co-Lead/EA/SDO→Orchestrator/Specialist role remap for the cf-program fleet; canonical ref lives in the *sunsetting* devplatform repo |
| project_cf_1_closed.md | **RETIRE→ARCHIVE** | cf-1 sprint closed-record (devplatform) |
| project_cf_1_5_closed.md (orphan) | **RETIRE→ARCHIVE** | cf-1.5 sprint closed-record (devplatform) |
| project_anthropic_primitive_cycle.md | **KEEP (demote)** | generic Anthropic-primitive-cadence fact; only the "cf kickoff" hook is retired — trim that line |
| feedback_mature_reframing_needs_sdv_amendment.md | **RETIRE→ARCHIVE** | SDV-amendment workflow = retired sprint cadence |
| feedback_manual_auditor_invocation_paused_fleet.md | **RETIRE→ARCHIVE** | Auditor wake-template = retired fleet flow |
| feedback_ea_numbering_global.md | **RETIRE→ARCHIVE** | "EA" numbering = retired EA fleet |

The transferable *judgment* inside these (standardize on industry names; don't self-baseline) is
already captured by `feedback_current_fleet_is_novice_mvp_not_baseline` (KEEP) — so archiving the
cf-mechanics loses nothing live.

### 3b. CONTRADICTED / SUPERSEDED by later decisions
| File | Disposition | Reason |
|---|---|---|
| project_pcr_seal_verify_declined.md | **MERGE→ project_no_full_hardware_rooted_trust** | strict subset; no_full_hardware (2026-07-15) is the SSOT and already links it |
| project_598_capstone_deep_dive.md (orphan) | **RETIRE→ARCHIVE** | "#598 NO-GO until…" intermediate state; superseded by `project_network_facing_future` (GO decided) + #107 already shipped |
| project_winui_mission.md (orphan) | **RETIRE→ARCHIVE** | 43-day-old shipped-status narrative; live-actionable bit survives in `project_winui_build_invocation` |
| project_active_projects_keeplist.md (orphan) | **UPDATE** | lists devplatform as active; CLAUDE.md (newer) says BEING SUNSET — refresh that line |

### 3c. DUPLICATE / OVERLAPPING pairs (consolidate)
| Cluster | Files | Disposition |
|---|---|---|
| Worktree cleanup | feedback_cleanup_worktrees_standard · feedback_worktree_cleanup_after_report_not_commit · feedback_merge_when_ready_and_cleanup | **MERGE 3→1** |
| Parallel execution | feedback_default_aggressive_parallel_execution · feedback_parallelize_freely_when_dedicated · feedback_parallel_by_default_for_disjoint_working_sets | **MERGE 3→1** (keep parallel_session_worktree_not_checkout separate — distinct git-safety point) |
| AO service authority | feedback_ao_runtime_service_management_ok · feedback_ao_restart_standing_blessing (orphan) | **MERGE 2→1** |
| Dispatch shipped-milestones | project_dispatch_690_691_shipped · project_dispatch_bestofn_689_shipped (orphan) · project_dispatch_merge_reliability_and_critical_loops (orphan) · project-714-dispatch-asset-generation (orphan) · project_from_source_gpu_build_proven (orphan) | **MERGE 5→1** "dispatch shipped features" (690_691 already the umbrella) |
| UC-010 | project_uc010_illustration_model · project_uc010_image_generation | KEEP both (distinct features) — low priority |

### 3d. ORPHANS (on disk, missing from MEMORY.md index) — reconcile the index
feedback_ao_restart_standing_blessing · feedback_dedicated_device_headless_app_not_a_blocker ·
feedback_never_rebase_resolve_via_merge · feedback_proactively_resolve_production_bugs ·
project-714-dispatch-asset-generation · project-headless-coding-swap-measurement ·
project_598_capstone_deep_dive · project_active_projects_keeplist · project_cf_1_5_closed ·
project_dispatch_bestofn_689_shipped · project_dispatch_merge_reliability_and_critical_loops ·
project_from_source_gpu_build_proven · project_winui_mission.
→ Several overlap with 3a/3b/3c (retire/merge those); the rest (never_rebase, dedicated_device,
proactively_resolve_production_bugs, swap-measurement) are KEEP — just add index lines.

**Net:** ~7 retire-to-archive (retired flow) + ~3 retire (superseded) + ~4 merge-clusters folding
~13 files → ~4, on 133 files ≈ a ~15% reduction, all suggestions only.

---

## 4. SKILLS / COMMANDS REGISTER

**Only THREE project-defined command/skill/agent files exist anywhere.** No files under user
`~/.claude/{commands,skills,agents}`; no files under `agentic-setup/.claude`. All three live in the
BlarAI main checkout and all three are heavy retired-world tug.

| File | Size | Retired-term hits | Tug flag |
|---|---|---|---|
| `.claude/commands/sprint-kickoff.md` | 11 KB | **25** | 🚩🚩 **STRONGEST** — puts session in *"Co-Lead Architect mode"*, drafts a *Strategic Design Vision (SDV)*, cites *DEC-15 protocol* |
| `.claude/commands/sprint-discovery.md` | 16 KB | 7 | 🚩 sprint-cadence discovery/BA flow |
| `.claude/commands/sprint-debrief.md` | 13 KB | 11 | 🚩 sprint-cadence debrief; "transition to next sprint kickoff" |

Terms grepped: SWAGR·SDV·SCR·Co-Lead·EA-#·devplatform·Auditor·Sprint Coordinator·Specialist·Orchestrator
→ **43 hits across the 3 files.**

These surface as the `/sprint-kickoff`, `/sprint-discovery`, `/sprint-debrief` skills. **Invoking any
one drops the session into the retired sprint cadence + the Co-Lead Architect persona** — exactly the
"tugged toward retired worlds" pull the LA reported, and it directly contradicts current CLAUDE.md
doctrine (LA/Claude WHY-HOW split, comprehension-gate flow, no Co-Lead persona, no SDV cadence).

**Nuance for the LA to weigh (not my call):** `docs/sprints/` and `ACTIVE_SPRINT.md` still exist, so
"sprints" as an organizing unit persist — but the *Co-Lead/SDV/DEC-15 mechanics* these commands encode
are the old devplatform cf-program style. So the tug is real even though the folder concept survives.
Recommend flagging all three as the #1 tug source; retire-or-rewrite is a governance decision.

The other listed skills (deep-research, dataviz, artifact-design, verify, code-review, frontend-design,
etc.) are Claude Code built-ins — no project tug, no flag.

---

## 5. TOP 5 ACTIONS (ranked)

1. **Retire/rewrite the 3 `sprint-*` commands** (`BlarAI/.claude/commands/`) — the single strongest
   backward tug; `/sprint-kickoff` literally boots "Co-Lead Architect mode + SDV." LA governance call.
2. **Clean the 10 MERGED-STALE BlarAI worktrees (~637 MB)** — all clean, all branch-in-main; leave the
   4 active/held (esp. #763-HELD; verify #843-c1-read-surface isn't superseded by merged c1-reconcile).
3. **Correct the brief premise + slim it** — it is a build-spec, NOT per-dispatch coder context (no
   script injects it); if coder bloat is the worry, audit `~/.config/opencode/AGENTS.md` instead. Slim
   the brief 51 KB→~18 KB by moving §10 lessons to LESSONS-LEARNED and cutting resolved landmines.
4. **Retire the ~7 cf-program/SDV/EA/Auditor memories + merge the 4 overlap-clusters** (§3a/§3c) and
   fold `project_pcr_seal_verify_declined` into `project_no_full_hardware_rooted_trust` (§3b).
5. **Reconcile MEMORY.md (13 orphans) + clean the 7 merged-stale agentic-setup worktrees** (removes all
   6 duplicate LESSONS-LEARNED copies in one motion); refresh the keeplist's stale "devplatform active"
   line.
