---
role: ea_code
phase: comprehension
revision: 1
tracking_task: 369
vikunja_comment: 541
posted_at: 2026-05-11T23:23:08Z
verdict: null
fleet_reports_task: 404
---

[agent:ea_code][phase:comprehension] **Sprint 10 EA-3 — devplatform Doctrine Authorship + SOP Portability Fix — Comprehension v1**

## Wake-template recitation

Operating under `C:\Users\mrbla\devplatform\tools\scheduled-tasks\templates\ea_code.md` — section headers in order:

- Vikunja label ID reference
- Phase 0 — Fleet-blocked exit
- Event-driven wake triggers (2-step protocol: Write trigger file at absolute path `C:\Users\mrbla\devplatform\tools\scheduled-tasks\triggers\sdo.wake`, then `schtasks /run /tn "\BlarAI\Wake SDO"`)
- Your scope for this firing
- State machine (Cases A–F)
- Formatting standard (DEC-14.5 — markdown headers, bullets, **bold** verdicts, ` ``` ` fenced code for paths/commands/hashes)
- Report emission (DEC-13 — disk copy + Fleet Reports project-8 task + commit + cross-reference trailer)
- M5 Comprehension Gate content (L-12 structural recitation + L-13 parent_head verify)
- Budget self-check, Exit criteria, Links

`--allowedTools` scope: `mcp__vikunja__*  Read  Write  Edit  Bash  mcp__git__*`. EA-3 also legitimately operates against the devplatform repo via `git -C "C:\Users\mrbla\devplatform" ...` and Read/Write under that tree per the prompt's `<working_directory_exception>` — the "do not cd elsewhere" worktree directive is explicitly overridden for this EA only.

## Parent-head verify (L-13)

- **BlarAI worktree HEAD** (verified): `87de454 [agent:sdo] move EA-3 prompt staging -> queue (Co-Lead APPROVED)`. EA-2 merge commit `1b1614e` is the cross-repo reference; my BlarAI metadata commits (ledger + sprint report) land on top of `87de454`.
- **devplatform main HEAD** (verified): `1a4713d fix(wake_protocol): final unprefixed 'Wake EA Code' in sdo.md:43 narrative` — matches the prompt's `<parent_head_devplatform>1a4713d</parent_head_devplatform>` exactly. My devplatform direct-to-main commit lands on top of this.

## EA prompt recitation

### Milestone objective (in my own words)

Author the three devplatform doctrine files (`CLAUDE.md`, `AGENTS.md`, `.github/copilot-instructions.md`) from scratch by overwriting the existing 2–4 line placeholder stubs. Content is driven by the EA-1 classification matrix (19 MOVE-devplatform rows + 7 MIRROR-both rows + 9 devplatform-only fresh rows = 35 row-equivalents) plus the 5 LA-arbitrated content directives in Vikunja task #369 comment #521. Each file ≥ 100 lines, mature-not-minimal — readable cold by a Cowork sandbox agent or cf-1 EA that has never seen BlarAI runtime context. Concurrently fix the `from tools.autonomy_budget import state` portability bug (SDV §4 success criterion #4) so that pause/resume invocations succeed from any working directory without a `$env:PYTHONPATH` workaround. Land all four devplatform artifacts (3 doctrine + 1 portability fix) in a single direct-to-main commit on devplatform whose body cross-references the BlarAI EA-2 merge commit `1b1614e`. On the BlarAI side, write a Q1-1 ledger entry and a sprint completion report, commit them on BlarAI main (no feature branch — metadata only).

**Downstream readers of post-EA-3 devplatform doctrine**: autonomous fleet sessions run by `wake_launcher.ps1` (SDO, Co-Lead, EA Code, Sprint Auditor); cf-1 EAs that will pick up the devplatform fleet refactor work later; any Cowork sandbox agent loaded with the devplatform repo. These readers will NOT have BlarAI's CLAUDE.md preloaded — devplatform doctrine must stand on its own and only cross-reference BlarAI for product-runtime-specific material (label IDs, ADRs, UCs, hardware, security mandates).

### Per-work-item summary (WI-1 through WI-7)

- **WI-1** — Author `devplatform/CLAUDE.md` ≥ 100 lines (target 200–300) with mandatory §sections in this order: Title, §Repo Identity, §Vikunja-Bridge, §Current-Active-Sprint, §Agent-Operating-Model, §Fleet-Pause-SOP, §DEC References, §Wake Templates, §Cross-References to BlarAI. The four hyphenated headers (`§Vikunja-Bridge`, `§Current-Active-Sprint`, `§Agent-Operating-Model`, `§Fleet-Pause-SOP`) MUST match BlarAI's post-EA-2 `*See also:*` pointers byte-exact for grep-able resolution.
- **WI-2** — Author `devplatform/AGENTS.md` ≥ 100 lines (target 120–180) per LA Directive A: dev/target framing, devplatform is fleet-infrastructure (not a runtime product), Claude/Codex/Copilot target two repos (BlarAI + devplatform), per-role fleet coordination expectations (SDO, Co-Lead, EA Code, Sprint Auditor), BlarAI explicitly framed as a Qwen3 product runtime in which Claude is NEVER part of the runtime.
- **WI-3** — Author `devplatform/.github/copilot-instructions.md` ≥ 100 lines (target 250–400) as well-formed XML mirroring BlarAI's envelope shape, with required envelopes: `<repo_identity>`, `<user_identity>` (Directive D), `<core_operating_principles>`, `<chat_role_taxonomy>` (4 roles: SDO, Co_Lead, EA, Sprint_Auditor), `<interaction_rules>` (MOVE rules #32f/h/j/k/l/n/o + MIRROR rules #32a/b/c/i/m/p), `<security_and_workflow_constraints>` (with full `<fleet_pause_sop>` body per Directive B), `<vikunja_task_tracking>` (with `<sdo_responsibilities>` + `<ea_responsibilities>` + `<co_lead_responsibilities>` + `<label_reference_pointer>` per Directive C — no numeric ID duplication), `<wake_template_summary>`, `<dec_references>`, `<control_signal>`.
- **WI-4** — Resolve the autonomy_budget import portability bug. Chosen technique: **option (c) — standalone CLI script `tools/autonomy_budget/cli.py`** invoked by absolute path. Verification = 3 working directories × 2 commands (pause/resume) = 6 invocations, zero `ModuleNotFoundError`, all stdouts captured.
- **WI-5** — Single devplatform direct-to-main commit (`git -C "C:\Users\mrbla\devplatform" ...` form preferred; explicit `git add <path>` per file — never `-A` — to avoid sweeping pre-existing dirty working-tree items per N-10). Commit body verbatim cross-references `1b1614e`.
- **WI-6** — BlarAI ledger entry at `docs/ledger/<ts>_sprint10_ea3_devplatform-doctrine-authorship.md` with Q1-1 frontmatter (predecessor = `20260511_222928_sprint10_ea2_blarai-strip`, verified on disk).
- **WI-7** — BlarAI sprint completion report at `docs/sprints/sprint_10/reports/<ts>_ea_code_completion_v1.md` containing per-WI disposition, 8 acceptance criteria with PASS/FAIL evidence, verification matrix outputs, cross-reference resolution audit, negative-constraint compliance. Commit on BlarAI main with `[sprint:10][role:ea_code][phase:completion]` tag.

### Negative constraints (recitation in my own words — N-1 through N-16)

N-1 no BlarAI doctrine edits (EA-2 scope, now frozen). N-2 no ADR / governance / runbook edits. N-3 no test or production code edits (services/, shared/, launcher/, tests/ off-limits). N-4 no repo rename or path restructure. N-5 no duplication of the canonical Vikunja label-id table — cross-reference BlarAI's table only. N-6 no BlarAI feature branch — ledger + report commit direct to BlarAI main. N-7 no edits to `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` (FROZEN at Entry 52). N-8 no Stage 6.7.5 retro-fix tickets created from EA-3 — findings recorded in completion report, LA triages. N-9 no push to either remote — local commits only. N-10 no staging of pre-existing devplatform dirty-working-tree items (state.json, wake-template XMLs, fleet_observability flags); explicit `git add <path>` per file. N-11 no XML malformedness — `ET.parse(...)` must exit 0. N-12 no padding to hit the ≥100 line floor — expand with concrete operational content from the matrix. N-13 no alteration of the LA-arbitrated Directives A–E — element names and section headers verbatim. N-14 no new Vikunja tickets from EA-3 for out-of-working-set findings. N-15 no touching `tools/vikunja_mcp/`, `tools/vikunja/`, services/, shared/, launcher/, phase2_gates/ — single allowed code touch is `tools/autonomy_budget/`. N-16 no pytest run — EA-3 verification is the 3-working-directory invocation matrix.

### Acceptance criteria recitation (8 items)

1. `devplatform/CLAUDE.md` ≥ 100 lines with EXACT hyphenated §sections `Current-Active-Sprint`, `Vikunja-Bridge`, `Agent-Operating-Model`, `Fleet-Pause-SOP`.
2. `devplatform/AGENTS.md` ≥ 100 lines with dev/target framing per Directive A.
3. `devplatform/.github/copilot-instructions.md` ≥ 100 lines, contains the LA-arbitrated XML elements (`<fleet_pause_sop>`, `<sdo_responsibilities>`, `<ea_responsibilities>`, `<co_lead_responsibilities>`, `<user_identity>`, `<label_reference_pointer>`), parses cleanly via `ET.parse(...)`.
4. SOP portability fix verified across 3 working dirs × 2 commands = 6 invocations, zero `ModuleNotFoundError`, all stdouts in completion report.
5. Ledger entry with Q1-1 frontmatter complete.
6. All 5 BlarAI post-EA-2 cross-reference pointers resolve cleanly (L68, L91, post-Active-State; XML L134-136 and L165) — completion-report audit lists each PASS/FAIL.
7. devplatform commit body contains `1b1614e` literal.
8. EA-3 sprint completion report committed on BlarAI main with completion phase tag.

## My plan of work (cross-referenced to WIs)

After SDO Phase 1a APPROVES this comprehension, my execution order is:

1. **Fleet pause** (pre-flight, BEFORE any devplatform write): `$env:PYTHONPATH = "C:\Users\mrbla\devplatform"; python -c "from tools.autonomy_budget import state; state.pause_fleet('Sprint 10 EA-3 devplatform doctrine authorship + SOP portability fix', updated_by='ea_code', path='C:/Users/mrbla/devplatform/tools/autonomy_budget/state.json')"` followed by an empty BlarAI commit `chore(ops): pause fleet -- Sprint 10 EA-3 devplatform doctrine authorship`. I accept the legacy `$env:PYTHONPATH` workaround for the pause itself — the new technique only becomes operational AFTER WI-4 lands.
2. **Read `tools/autonomy_budget/state.py`** (referenced via `git -C "C:\Users\mrbla\devplatform"`) to confirm `pause_fleet` and `resume_fleet` signatures and import shape; adapt the WI-4 cli.py sketch to match the real API.
3. **WI-4 first** (portability fix `tools/autonomy_budget/cli.py`) — landing this early lets WI-3's `<fleet_pause_sop>` body cite the new, working invocation in the doctrine rather than the legacy workaround.
4. **WI-4 verification matrix** — 3 working dirs × 2 cmds = 6 invocations; capture all 6 stdouts to a temp note for later inclusion in the completion report. Sequence the 3 pause/resume cycles so the final state is `resumed`; if a pause is needed for the rest of WI-1/2/3 work, re-pause via the new (now operational) cli.py after verification.
5. **WI-1 author `devplatform/CLAUDE.md`** — overwrite the 4-line stub with the structured doctrine. Headers byte-exact for grep resolution.
6. **WI-2 author `devplatform/AGENTS.md`** — overwrite the 2-line stub with Directive A content; ≥ 100 lines.
7. **WI-3 author `devplatform/.github/copilot-instructions.md`** — overwrite the 2-line stub with the XML envelope structure including the full `<fleet_pause_sop>` body referencing the post-WI-4 cli.py invocation. Verify via `python -c "import xml.etree.ElementTree as ET; ET.parse(r'...')"` after authoring; iterate if malformed.
8. **Cross-reference resolution audit** (Quality Gate step 5) — grep each of the 5 BlarAI pointers against my devplatform files; any DANGLING fix before commit.
9. **WI-5 devplatform commit** — explicit `git -C "C:\Users\mrbla\devplatform" add CLAUDE.md AGENTS.md .github/copilot-instructions.md tools/autonomy_budget/cli.py` (no `-A`), `git status` to confirm only intended paths staged, `git commit` with subject + body containing `1b1614e` literal, capture commit hash.
10. **WI-6 ledger entry** on BlarAI worktree with Q1-1 frontmatter; predecessor = `20260511_222928_sprint10_ea2_blarai-strip` (verified on disk).
11. **WI-7 sprint completion report** on BlarAI worktree — per-WI disposition, 8 AC items with evidence, verification matrix outputs, cross-reference audit, negative-constraint compliance.
12. **BlarAI metadata commit** (direct to main per N-6) — `[sprint:10][role:ea_code][phase:completion] EA-3 sprint completion report + ledger entry`.
13. **Fleet resume** — using the new operational cli.py (`python C:\Users\mrbla\devplatform\tools\autonomy_budget\cli.py resume --updated-by ea_code`) followed by empty BlarAI commit.
14. **Vikunja completion comment** on task #369 with all mandated subitems; apply `Gate:Pending-SDO` (id 9); fire SDO event-driven wake (`Write` trigger file → `schtasks /run`); exit cleanly.

## Files to create/modify (absolute paths)

### devplatform writes (4)

- `C:\Users\mrbla\devplatform\CLAUDE.md` — overwrite (placeholder stub → ≥ 100 line doctrine)
- `C:\Users\mrbla\devplatform\AGENTS.md` — overwrite (placeholder stub → ≥ 100 line dev/target framing)
- `C:\Users\mrbla\devplatform\.github\copilot-instructions.md` — overwrite (placeholder stub → ≥ 100 line XML doctrine)
- `C:\Users\mrbla\devplatform\tools\autonomy_budget\cli.py` — new (standalone CLI portability fix)

### BlarAI writes (2)

- `C:\Users\mrbla\BlarAI\docs\ledger\<ts>_sprint10_ea3_devplatform-doctrine-authorship.md` — new Q1-1 ledger entry
- `C:\Users\mrbla\BlarAI\docs\sprints\sprint_10\reports\<ts>_ea_code_completion_v1.md` — new sprint completion report

`<ts>` = UTC `YYYYMMDD_HHMMSS` captured at execution time (likely `20260511_233xxx` if execution begins shortly after SDO approval; will adjust if execution slips materially).

## Source files to read

- `docs/sprints/sprint_10/strategic_design_vision.md` (SDV — §4 #2/#4, §5.1 #3, §5.3, §7 EA-3 row, §9, §13)
- `docs/sprints/sprint_10/doctrine_classification_matrix.md` (EA-1 deliverable — 19 MOVE rows + 7 MIRROR rows + 9 devplatform-only fresh rows)
- `docs/scheduled/ea_queue/P5_TASK10_EA2_BLARAI_STRIP.xml` (structural template + LA-arbitrated content blocks for cross-consistency)
- Vikunja task #369 comment #521 (LA arbitration verbatim — already embedded in this EA-3 prompt §la_arbitrated_directives, no re-fetch required)
- `C:\Users\mrbla\BlarAI\CLAUDE.md` (post-EA-2 — to verify cross-reference pointer text byte-exact)
- `C:\Users\mrbla\BlarAI\.github\copilot-instructions.md` (post-EA-2 — XML pointer element text byte-exact)
- `C:\Users\mrbla\BlarAI\AGENTS.md` (post-EA-2 12-line LA-arbitrated content — for dev/target framing parallel structure)
- `C:\Users\mrbla\devplatform\CLAUDE.md`, `AGENTS.md`, `.github\copilot-instructions.md` (placeholder stubs — confirm overwrite scope)
- `C:\Users\mrbla\devplatform\tools\autonomy_budget\state.py` (to match `pause_fleet` / `resume_fleet` signatures in cli.py)
- `C:\Users\mrbla\devplatform\tools\autonomy_budget\config.yaml` (only if config-level fix needed — not anticipated for option (c))

## Classification matrix recitation (verbatim)

- **MOVE-devplatform row count**: **19**
- **MIRROR-both row count**: **7**
- **Total content rows EA-3 authors fresh in devplatform**: 19 (MOVE) + 7 (MIRROR devplatform-side authoring) + 9 (rows #45-53, devplatform-only fresh content with no BlarAI source) = **35 row-equivalents** distributed across the three devplatform files.

## EXACT deliverable structure (verbatim recitation)

- No BlarAI feature branch for EA-3 work (no BlarAI source-doctrine writes — only metadata ledger + report).
- devplatform commit pattern: direct to main, single commit per the commit_template.
- BlarAI ledger entry filename pattern: `docs/ledger/<ts>_sprint10_ea3_devplatform-doctrine-authorship.md` (UTC stamp captured at execution).
- BlarAI sprint report filename pattern: `docs/sprints/sprint_10/reports/<ts>_ea_code_completion_v1.md`.
- Three devplatform doctrine files OVERWRITE the existing placeholder stubs (per matrix §4 F-2).
- Each devplatform doctrine file ≥ 100 lines (SDV §4 #2, §5.3 mature-not-minimal floor).

## ORACLE expectation (L-12 ACTION-3) — verbatim

```powershell
git -C "C:\Users\mrbla\devplatform" diff 1a4713d..HEAD --name-only
```

Must output exactly (sorted):

```
.github/copilot-instructions.md
AGENTS.md
CLAUDE.md
tools/autonomy_budget/cli.py
```

BlarAI-side ORACLE:

```powershell
git -C "C:\Users\mrbla\BlarAI" diff 1b1614e..HEAD --name-only
```

Must output exactly (sorted):

```
docs/ledger/<ts>_sprint10_ea3_devplatform-doctrine-authorship.md
docs/sprints/sprint_10/reports/<ts>_ea_code_completion_v1.md
```

(Note: comprehension-report disk write committed during the comprehension phase is ALSO on BlarAI main between `1b1614e` and EA-3-completion HEAD. The acceptance-criteria #8 ORACLE references `1b1614e..HEAD` which will additionally include the comprehension-report file `docs/sprints/sprint_10/reports/20260511_232308_ea_code_comprehension_v1.md` and the Fleet Reports report commit. This is expected for DEC-13 — comprehension reports are committed mid-phase. I will note this expected delta in my completion report's ORACLE-BlarAI section.)

## Working-set declaration (L-15 verbatim)

"I write to exactly six paths: three devplatform doctrine files, one (or more) devplatform portability-fix artifact, one BlarAI ledger entry, one BlarAI sprint completion report. I read the SDV, the classification matrix, the EA-2 prompt, the three post-EA-2 BlarAI doctrine files, the three devplatform placeholder stubs, and the autonomy_budget code. I touch NO other path in either repo. If I discover a defect outside the working set (e.g., a stale runbook reference in BlarAI's docs/runbooks/, a typo in an ADR), I STOP and document in my completion report; I do not freelance."

(Caveat: the DEC-13 comprehension-report + Fleet Reports commit lands during the comprehension phase, before SDO approval — that disk-write and commit ARE the working-set artifacts for Phase 1a and are mandated by the wake template, distinct from the milestone working set above.)

## Cross-repo ordering acknowledgment (L-19 verbatim)

"EA-2 has already landed on BlarAI main at commit `1b1614e`. EA-3 commits to devplatform main second. My devplatform commit body explicitly cross-references the BlarAI EA-2 merge commit `1b1614e`. I do NOT push to either remote. I do NOT touch BlarAI doctrine files — they were EA-2's scope and are now frozen for the remainder of Sprint 10."

## Mature-not-minimal acknowledgment (L-22 verbatim)

"Mature not minimal: each devplatform doctrine file is a coherent operational reference in its own right, readable standalone by a cf-1 EA or a Cowork sandbox agent that has never seen BlarAI runtime context. Floor: ≥ 100 lines per file. Target: substantive content, not padding. If a file approaches the floor only with placeholder bullet points or restated cross-references, I expand with concrete operational guidance from the matrix rows (MOVE-devplatform content) and from the SDV §5.3 (a)-(i) fleet-doctrine enumeration. Mature-not-minimal does NOT mean prolix — it means content density at the floor."

## LA-arbitration acknowledgment (5 directives in my own words)

- **(A) Row #41 — `devplatform/AGENTS.md`**: mirror the dev/target boundary framing from BlarAI/AGENTS.md; devplatform is the fleet-infrastructure repo (NOT a runtime product); Claude/Codex/Copilot are dev-side agents targeting two repos (BlarAI product runtime + this devplatform fleet infra repo); BlarAI is explicitly framed as a Qwen3 product runtime in which Claude is NEVER part of the runtime; per-role fleet-coordination expectations laid out for SDO, Co-Lead, EA Code, Sprint Auditor; ≥ 100 lines.
- **(B) IR-9 — `<fleet_pause_sop>` ownership**: devplatform/.github/copilot-instructions.md OWNS the full `<fleet_pause_sop name="LA_Fleet_Pause_SOP">` element (with `<trigger_conditions>`, `<pause_command>`, `<resume_command>`, `<verification_step>`, `<la_coordination_note>`, `<trivial_edit_exception>`, `<decision_table>` children); BlarAI's `<fleet_pause_sop_pointer>` at L134-136 resolves here; element names intentionally distinct to avoid grep collision.
- **(C) Row #37 — Vikunja envelope split (Option A)**: devplatform/.github/copilot-instructions.md owns `<sdo_responsibilities>` + `<ea_responsibilities>` + `<co_lead_responsibilities>` envelopes (full bodies); the canonical Vikunja label-id table stays in BlarAI/CLAUDE.md §Vikunja Conventions; devplatform adds `<label_reference_pointer>` cross-referencing BlarAI for the numeric IDs (NO duplication).
- **(D) Row #27 — `<user_identity>` MIRROR-both**: devplatform/.github/copilot-instructions.md includes its own `<user_identity>` block (LA role, vibe-coder profile, Win11/PowerShell environment, LA workflow, communication preferences per `feedback_no_commendations` + `feedback_spell_out_acronyms`) — same LA framing as BlarAI's mirror, devplatform-context phrasing.
- **(E) Row #12 — §Current-Active-Sprint authorship**: devplatform/CLAUDE.md §Current-Active-Sprint authors the fleet sprint-lifecycle doctrine (how `docs/sprints/ACTIVE_SPRINT.md` is read — that file stays in BlarAI; how `docs/active_tasks.yaml` is the roster source of truth; DEC-15 sprint lifecycle; derived paths table; per-agent SDV readers; what the pattern does NOT do; template references); header text EXACTLY `## Current-Active-Sprint` (or `### Current-Active-Sprint`) — case-sensitive, hyphenated, for grep-able resolution of BlarAI/CLAUDE.md L91 `*See also:*` pointer.

## Cross-reference resolution audit acknowledgment

EA-3's devplatform doctrine MUST satisfy these BlarAI post-EA-2 pointers (each verified live on disk at audit-time):

- `BlarAI/CLAUDE.md` L68 → `*See also: C:\Users\mrbla\devplatform\CLAUDE.md §Vikunja-Bridge.*` — must resolve to a `## Vikunja-Bridge` (or `### Vikunja-Bridge`) section in `devplatform/CLAUDE.md`.
- `BlarAI/CLAUDE.md` L91 → `*See also: C:\Users\mrbla\devplatform\CLAUDE.md §Current-Active-Sprint.*` — must resolve to `## Current-Active-Sprint` (or `###`).
- `BlarAI/CLAUDE.md` (post-Active-State) → `*See also: C:\Users\mrbla\devplatform\CLAUDE.md §Agent-Operating-Model and §Fleet-Pause-SOP.*` — must resolve to BOTH `## Agent-Operating-Model` AND `## Fleet-Pause-SOP` (or `###` for either).
- `BlarAI/.github/copilot-instructions.md` L134-136 `<fleet_pause_sop_pointer>` → must resolve to `<fleet_pause_sop>` in devplatform XML.
- `BlarAI/.github/copilot-instructions.md` L165 `<fleet_responsibilities_pointer>` → must resolve to `<vikunja_task_tracking>` envelope in devplatform XML (containing `<sdo_responsibilities>` + `<ea_responsibilities>` per Directive C).

The grep-based verification commands (Quality Gate step 5) will be executed pre-commit and listed in the completion report with RESOLVED/DANGLING per pointer.

## Portability-fix technique choice (gate item #13)

**Chosen technique: option (c) — standalone CLI script `tools/autonomy_budget/cli.py`** invoked by absolute path.

**Rationale** (2 sentences): SDV §9.2 #3 defaults to (c) as "likely (c) given Stage 6.7.5's PS1-script-with-env-var pattern", and the prompt's WI-4 implementation sketch is built around (c) — using it avoids re-designing the doctrine's `<pause_command>` / `<resume_command>` examples. Option (c) also has the cleanest portability mechanic (Python's `sys.path[0]` becomes the script's containing directory when invoked by absolute path, so a single `sys.path.insert(0, _REPO_ROOT)` in cli.py — where `_REPO_ROOT = Path(__file__).resolve().parents[2]` — makes `from tools.autonomy_budget import state` resolve regardless of cwd or environment variables).

I will verify `state.py`'s actual `pause_fleet` / `resume_fleet` signatures before authoring cli.py and adapt the argparse subparsers to match. If `state.py`'s signature uses keyword-only arguments or non-default `path` semantics that the WI-4 sketch doesn't capture, I'll document the adaptation in the completion report.

## Risks and ambiguities

- **R1 — Content density per file**: hitting ≥ 100 lines per file is straightforward; hitting the *mature* target (200-300 / 120-180 / 250-400) without padding requires drawing extensively on matrix MOVE rows. I anticipate `<fleet_pause_sop>` body alone is \~50 lines (7 required children); `<vikunja_task_tracking>` is another \~60-80 lines; `<chat_role_taxonomy>` with 4 roles \~40 lines. The XML file will likely hit 300-400 lines naturally. CLAUDE.md's tighter (≥25 line) §Current-Active-Sprint requirement plus §Agent-Operating-Model (≥30 lines, Tier 1/2/3 + DEC-12 lattice + gate-label semantics) plus §Vikunja-Bridge (≥15 lines) etc. — also hits target naturally.
- **R2 — `state.py` API shape**: the WI-4 sketch assumes `state.pause_fleet(reason, updated_by=, path=)` and `state.resume_fleet(updated_by=, path=)` — same signatures used in the pre-flight pause workaround. If the actual API differs, I'll adapt cli.py and document. No comprehension-level ambiguity, just an implementation detail to verify against the live code.
- **R3 — Pre-existing devplatform dirty working tree**: N-10 explicitly calls out state.json mutations, wake-template XML edits, and fleet_observability flags as pre-existing artifacts NOT to be swept into EA-3's commit. I'll use explicit `git add <path>` per file and verify post-staging via `git status`. If `state.py` itself has pending edits that conflict with cli.py — I'll STOP and document, NOT silently merge.
- **R4 — Comprehension-report commit and ORACLE-BlarAI delta**: per DEC-13 + DEC-15, I commit this comprehension report to BlarAI main BEFORE SDO Phase 1a review. That commit (plus the Fleet Reports task creation commit) means the BlarAI-side ORACLE `git diff 1b1614e..HEAD --name-only` at completion time will include the comprehension-report file AND the completion-report file AND the ledger entry — three files, not two. This is the expected DEC-13 pattern (EA-2's run produced the same shape); I'll cite the delta explicitly in the completion report's ORACLE-BlarAI section so SDO does not flag it as a violation.
- **R5 — Cross-reference text byte-exactness**: BlarAI/CLAUDE.md may use slightly different cross-reference phrasing than my recall — I'll verify each of the 5 pointers byte-exact via `Select-String` before authoring my devplatform headers, and only then write the headers. If the pointer text says `§Vikunja-Bridge` with a hyphen, my header is `## Vikunja-Bridge` (hyphenated); if pointer says `§Vikunja Bridge` with a space, my header is `## Vikunja Bridge` (spaced). The matrix uses hyphens consistently and the prompt confirms hyphenated; I'll spot-check on disk.
- **R6 — devplatform pause command in the SOP doctrine reflects post-fix state**: Directive B says the `<pause_command>` example in the SOP body should use EA-3's chosen technique (post-fix), NOT the legacy `$env:PYTHONPATH` workaround. This means WI-4 (cli.py authoring) must land *before* WI-3 (XML doctrine) so I have a concrete invocation to embed. I've sequenced my plan-of-work to land WI-4 first.
- **R7 — Wake-template path verification**: WI-1's §Wake Templates §section references `C:\Users\mrbla\devplatform\tools\scheduled-tasks\templates\`. The wake-template I'm currently operating under is the `ea_code` template at that path, which I read directly from this session — but I'll verify the directory contains all 4 templates (sdo, co_lead, ea_code, sprint_auditor) before authoring the §Wake Templates §section.
- **R8 — XML mirroring vs. fresh content**: WI-3's `<interaction_rules>` envelope mixes MOVE rules (#32f/h/j/k/l/n/o — 7 rules) and MIRROR rules (#32a/b/c/i/m/p — 6 rules); MIRROR-both rules MUST appear on the devplatform side too (matrix designation). I'll author each rule body fresh (not literally `git mv` from BlarAI's pre-EA-2 doctrine since that no longer exists in BlarAI), driving content from the matrix row description and (for MIRROR rules) from the post-EA-2 BlarAI XML's retained rule bodies.

## Out-of-working-set prohibition acknowledgment (L-15 verbatim)

"DO NOT modify any file outside [3 devplatform doctrine files, devplatform portability-fix artifact(s), BlarAI ledger entry, BlarAI sprint completion report]. DO NOT touch BlarAI doctrine files (EA-2 scope, now frozen). DO NOT amend ADRs, governance docs, runbooks, test code, production code, services/, shared/, launcher/. DO NOT touch `docs/POST_OPERATIONAL_MATURATION_LEDGER.md` (FROZEN). DO NOT create Stage 6.7.5 retro-fix tickets — those flow through SDO Stage 6.7.5 backlog separately. If a non-working-set change appears necessary, STOP, document the blocker in my completion report, and wait for SDO direction."

## Stop and wait

Per the wake template and SDV: applying `Gate:Pending-SDO` (id 9) and removing `Gate:Pending-Execution` (id 16) on Vikunja task #369 next, then writing the DEC-13 report artifacts, then exiting cleanly. WILL NOT execute any WI until SDO Phase 1a posts `VERDICT: APPROVED` and `Gate:Approved` (id 12) appears on the task.
