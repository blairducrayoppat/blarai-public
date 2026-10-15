---
title: Where knowledge is kept: folder catalogue (2026-10-11)
status: living
area: research
---

# BlarAI knowledge catalogue (draft) - where knowledge is kept

Measured 2026-10-11 against the main checkout C:/Users/mrbla/BlarAI (branch main). Read-only survey.
"Tracked" = files git tracks; "on disk" = files present (includes git-ignored). Dates are git first-add to last-change unless stated.
Acronyms: ADR = Architecture Decision Record. DEC = a numbered runtime configuration decision. LA = Lead Architect. SSOT = single source of truth.

## 1. Summary (10 lines)

1. Knowledge sits in four layers: root long-form logs (journal, lessons, field notes, performance log, use cases), docs/ (24 folders), working folders outside docs/ (evals/, phase2_gates/, tools/, scripts/, with a few READMEs), and the Vikunja ticket board (not in the repo).
2. The master map, docs/INDEX.md (129 lines), has no dead links but is stale: wrong file counts for most folders (adrs says 34, actual 46; performance says 140, actual 741), says docs/demo and docs/handoffs hold nothing (demo has 1 tracked file; handoffs has 221 on-disk files, none tracked), and lists three root files that now live in docs/reference/.
3. Five folders are not mentioned in docs/INDEX.md at all: blairproweb, evidence, quality, reviews (193 files, second-largest living folder), validation.
4. Folders with a real own index: archive (per-surface INDEX or README), governance, journal_fragments, ledger, guide-workstreams, reference, runbooks (LA_OPERATIONS_INDEX.md, but 21 of 31 other runbooks are missing from it). No own index: adrs (DECISION_REGISTER indexes them but 8 of 45 ADR numbers are absent), design, research (298 files), reviews, security, reports, upstream, performance (only per-subfolder READMEs), evidence, quality, validation, battery, demo, blairproweb.
5. Topic-search surfaces that exist: the LESSONS.md one-line index (380 lines), BUILD_JOURNAL "Plain summary" lines plus docs/archive/journal/INDEX.md, FIELD_NOTES section headings, and the ticket-number filename prefix (181 tracked docs files). Frontmatter (title/status/area) is partial: 0% in adrs, security, upstream, guide-workstreams; 100% in reports; 94% in ledger; 28-38% in research, reviews, governance.
6. The rules say each kind of knowledge has one home: CLAUDE.md, .claude/rules/*.md (7 files, 139 lines), docs/governance/doc-lifecycle.md. Section 5 tabulates them with quoted rule text. Studies and research have no single stated home.
7. Duplicates: two decision registers (BlarAI and devplatform); eight DEC rows point at a file that moved; journal in four shelves; lessons in three; performance in four places; ledger in three; INDEX contradicts itself on three root files.
8. Off-git, unindexed knowledge exists: about 25 root PDFs/HTML/CSV papers, Intel Whitepapers/, Temp Files/ (139 files), docs/handoffs/ (221), 4 stray docs/*.xml/.log files, userdata/. A map built from git alone misses them.
9. Vikunja holds the live queue, ticket decisions, CURRENT STATE comments, dead-end notes and blocked-by predicates; the repo cites ticket numbers only. Not queried.
10. Could not verify: Vikunja contents and counts, intent behind git-ignored files, per-file topic coverage (no content classification run).

## 2. Repo-root documents

| Item | Holds | Size / dates | Writer and when | Index today | In docs/INDEX.md? | Kind | Find-by-topic |
|---|---|---|---|---|---|---|---|
| CLAUDE.md | Standing instructions for every Claude session plus the dated status snapshot | 288 lines; 2026-04-19..2026-10-09 | Merging session; snapshot refreshed at merge clusters; changes follow .claude/rules/doctrine.md | <rules_index> section; generated docs/governance/rules-corpus.yaml | Yes (section 1) | state + rules | Tag sections; grep. Rules corpus gives one record per rule. |
| LESSONS.md | Transferable judgment lessons: Rules, Canonical Tier, Canon-32, one-line index | 680 lines; 2026-07-03..2026-10-06; numbers up to 385 (380 index lines; 344-348 reserved) | Integrator session at fold time; numbers serial, never renumbered | Own "Index of every lesson" (line 292 on) | Yes | lesson | Good: one line per lesson with recurrence and control flags. Full text in docs/archive/lessons/LESSONS_ARCHIVE.md (777 lines, one heading, grep only). |
| FIELD_NOTES.md | Mechanical gotchas (API traps, engine quirks, driver and tool behaviour) | 1478 lines, 19 level-2 sections; 2026-07-03..2026-10-07 | Any session when a mechanic is learned | Section headings only | Yes | how-to / gotcha | Medium: early sections are topics (Python, Windows, WinUI, Hyper-V, Git, Vikunja API); later ones are dated incident titles. |
| BUILD_JOURNAL.md | First-person build narrative, current month only (5 entries, 2026-10-05..06) | 172 lines; 2026-05-21..2026-10-09 | Single session on a quiet tree directly; parallel sessions via fragments | "Plain summary" line per entry; rotated months in docs/archive/journal/INDEX.md | Yes | narrative / rationale | Medium: grep summary lines; archive INDEX is date / title / summary / volume. Archive volumes hold 15, 239, 326, 63, 48 headings (2026-05..09). |
| PERFORMANCE_LOG.md | Human-readable measurement narratives, community-grade | 4947 lines; 2026-05-21..2026-10-11; 90 dated headings | Session that ran the measurement, at run time | None; no rotation yet | Yes | measurement | Weak: dated headings only; pairs with JSON in docs/performance/. |
| Use Cases_FINAL.md | Canonical use case definitions (product vision) with dated amendments | 610 lines; 2026-02-23..2026-07-15 | LA-directed amendments | None | Yes | decision / vision | Weak: long prose; use case ids are the handle. |
| README.md | Public framing and "Recent advancements" | 381 lines; 2026-07-03..2026-10-09 | Session at merge clusters | None | Yes | state (public) | n/a |
| AGENTS.md | Pointer for non-Claude agents to CLAUDE.md | 23 lines; last 2026-05-14 | Rare | None | Yes | pointer (stale: describes the cf-3 fleet, which CLAUDE.md says is being sunset) | n/a |
| SECURITY.md, LICENSE.md, COMMERCIAL-LICENSE.md | Security policy, licences | 24, 79, 24 lines | Rare | None | Yes | policy | n/a |
| Enabling XAttention on Intel Arc - Gemini Study.md | Long-form study | 128 lines; git-ignored | Once | None | Listed as repo-root file but ignored | study | n/a |
| Root PDFs, HTML, CSV, xlsx (about 25: agent-security papers, Intel TDX reports, OpenVINO release notes, model-support CSVs, Test Matrix.xlsx) | A research-literature shelf and reference data | git-ignored, on disk only (`git ls-files '*.pdf'` = 0) | Operator | None | No | study (third party) | None; filename only. |
| Intel Whitepapers/ (1), Temp Files/ (139), userdata/ (93 on disk, 1 tracked README), github_profile_README.md | Operator-side scratch and source material | git-ignored | Operator | userdata/README.md only | No | misc | n/a |

## 3. docs/

### 3.0 docs top level (20 tracked .md files plus 5 untracked stray files)
Tracked: INDEX, DECISION_REGISTER (129 lines), ROADMAP, TEST_GOVERNANCE, BUILD_JOURNAL_ANTHOLOGY (3564 lines), SECURITY_ASSESSMENT, TEST_AUDIT_FINDINGS, GAP_TO_OPERATIONAL_REPORT, HOWTO_FEATURES_NON_DEV, RUNBOOK_NON_DEV_OPERATIONS, FLEET_DISPATCH_LOG, LEARNING_LOOPS_PROGRAM_DESIGN, MODEL_EVALUATION_GEMMA4_12B and STANDARDS_Conformance_Audit (both absent from INDEX section 2), MODEL_EVALUATION_QWEN36_27B, MODEL_SHARING_INVESTIGATION, POST_OPERATIONAL_MATURATION_LEDGER (stub), openvino_2026.2_upgrade_opportunity_catalog, eagle3_conversion_findings_2026-06-29, uc010_dispatch_asset_pipeline. Untracked, on disk: Task4.1_v1.xml, Task4.2_v1.xml, Task4.2_combined_v1.xml, Task4.2b_v1.xml, "Status Update after 4.2x and EAGLE-3 test.xml", _claude_projects_dirty.log.
Index: docs/INDEX.md sections 1-4. Mixed kinds: decision, state, study, how-to, measurement.

### 3.1 Folder table (counts by git ls-files; dates first add..last change)

| Folder | Holds | Files (tracked / on disk), dates | Who writes, when | Own index | In docs/INDEX.md | Kind | Find-by-topic |
|---|---|---|---|---|---|---|---|
| adrs | One file per ADR (ADR-005 onward), rationale and rejected alternatives; one DRAFT_ file | 46 / 46; 2026-02-23..2026-10-11 | Session making a trust, security or architecture decision; ADR plus DECISION_REGISTER row in the same change | None (DECISION_REGISTER acts as index; absent from it: ADR-006, 007, 008, 009, 010, 012, 014, 019) | Yes (count stale: 34) | decision | Good by number; no topic list; 0 of 46 have frontmatter. |
| archive | Retired material: journal volumes, lessons archive, ledger monolith, sprints 8-17, 141-file phase5-prompts cluster, platform_separation, scheduled XML, root-debris | 583 / 583 (395 md, 177 xml); 2026-05-08..2026-10-08 | Monthly rotation (tools/doc_hygiene/rotate_log.py) and doc-lifecycle moves | Per surface: journal/INDEX.md, sprints/INDEX.md, READMEs in 2026/phase5-prompts, retired_fleet_*, root-debris, scheduled. None for ledger, lessons, platform_separation, testing | Yes (17 refs) | history (all kinds) | Good for journal; weak for phase5-prompts (README only). |
| battery | Prescope for the overnight battery campaign | 1 / 1; 2026-07-06 | One-off | None | Yes (campaign cancelled, DEC-14) | study (stale) | n/a |
| blairproweb | JOURNAL.md for the website validation exercise | 1 / 1; 2026-08-30..08-31 | One session | None | NO | narrative | n/a |
| demo | PORTFOLIO_DEMO_PLAN.md | 1 / 1; 2026-07-30 | One-off | None | Yes, but INDEX says "0 (gitignored)" | plan | n/a |
| design | Design documents (outbound content control, provenance egress, coder containment overview, coder Definition of Done, class cure, advanced intake) plus july.15.2026 whole-system design review (6 files, own README) | 17 / 17; 2026-06-21..2026-10-09 | Designing session before building | None (july.15.2026 has README) | Yes (count 17 correct) | decision / study | Weak: names carry ticket and topic. CODER_DEFINITION_OF_DONE.md is the coder status SSOT. 8 of 17 have frontmatter. |
| evidence | Raw evidence for two dispatch defects (#1071, #1075) and a fleet timing sweep | 5 / 5; 2026-07-30 | One-off | None | NO | measurement | n/a |
| governance | Subsystem doctrine (rule engine, circuit breaker, IPC protocol, session state, weight integrity ...), doc-lifecycle, style, handoff template, rules-corpus files, agent-doctrine-evidence (incident stories behind rules), NIST PDFs, morning-read and overnight reports | 45 / 48; 2026-04-22..2026-10-08 | Designing session; evidence file appended in the same motion as a rule | README.md (domain inventory; says 16 domain docs, folder now holds 35 md) | Yes (count 17 stale) | decision / how-to / state | Medium: README audience matrix; frontmatter 9 of 35. |
| guide-workstreams | Trackers for OpenVINO upstream contribution (npu-int8-guard, upstream-shepherding with dated cycle folders) | 37 / 37; 2026-05-12..2026-07-30 | Upstream-contribution sessions | README at top and per workstream | Yes (count 18 stale) | state / study | OK within a workstream. |
| handoffs | Landing cards and handoff briefs (git-ignored) | 0 / 221; file mtimes 2026-05-22..2026-10-09 | Session at landing (handoff.md; template in governance) | None | Yes (marked 0 files: wrong) | state (transient) | Name only. |
| journal_fragments | Inbox of journal entries awaiting fold into BUILD_JOURNAL | 27 / 27; 2026-06-05..2026-10-11 | Any parallel session; integrator folds and deletes at lulls | README.md (SOP) | Yes (count 6 stale) | narrative (pending) | Filename = date-ticket-title. |
| learning | Presentation decks (fable5_deck, lessons_deck) | 25 / 29; 2026-06-10..2026-07-03 | One-off | README per deck | Yes | learning | n/a |
| ledger | One file per milestone (timestamp, sprint, EA, slug); none added since 2026-07-03 | 31 / 31; 2026-04-22..2026-07-03 | Session finishing a milestone | README.md (naming and frontmatter); 29 of 31 have frontmatter | Yes (4 refs) | state (milestones) | Frontmatter (ledger_id, date, sprint_id) permits structured search. |
| performance | Measurement data (521 json, 106 jsonl, 29 csv) in flat files plus per-run folders and a Hugging Face community export | 741 / 742; 2026-05-21..2026-10-11 | Session running a measurement; dataset upload to Hugging Face | READMEs in about 10 subfolders and 2 loose; subjects/README.md; community_export/README.md (dataset card). No top-level index | Yes (count 140 stale) | measurement | Weak at top (700+ files named probe_date.json); moderate inside subfolders. Pairs with PERFORMANCE_LOG.md. |
| quality | dispatch-quality-ledger.md | 1 / 1; 2026-07-15..07-24 | Dispatch sessions | None | NO | measurement | n/a |
| reference | Frozen studies moved off the repo root 2026-07-19 (risk assessment, red-team design review, Phase-2 test plan, winui3 field notes) | 5 / 5; 2026-07-19..07-20 | Frozen | README.md | Yes, but INDEX section 1 still lists three of them as repo-root | study | By title. |
| reports | Retired-fleet reports (SDO firing-exit v1-v7, corrective_actions, task_28) | 38 / 38; 2026-04-21..2026-07-03 | Retired process; closed | None | Yes | history | Frontmatter on all 36 md. |
| research | Dated research: coordinator program, containment evidence (windows containment comparison, MXC library study, wfp spike), publication program, agent-governance landscape, qwen35 verdicts, OpenVINO release relevance, Kagi, RAM headroom; with json and ps1 fixtures | 298 / 303 (131 md, 127 json, 20 ps1); 2026-06-04..2026-10-11 | Researching session, design-only | None at top; READMEs inside containment-evidence, doc-infrastructure-audit-2026-07, publication-program, mxc-library-study | Yes (count 16 stale) | study | Weak: about 60 top-level files, topic and date in the filename; frontmatter 39 of 131 md. doc-infrastructure-audit-2026-07 is an earlier look at this same problem. |
| reviews | Independent review outputs and DISPOSITION RECORDS (one row per finding: FIXED / DEFERRED / REJECTED), checked by scripts/verify_disposition.py | 193 / 195 (139 md, 51 py); 2026-07-12..2026-10-11; 114 files named *disposition* | Reviewing session; required by CLAUDE.md deferral_discipline | None | NO | decision (finding outcomes) | Medium: filename = ticket-topic-disposition-date; disposition blocks are machine-readable; frontmatter 52 of 139. Two files untracked now. |
| runbooks | Operator and LA runbooks: go-live ceremonies, reboot, disaster recovery, VM lifecycle, Kagi key, manifest signing | 32 / 32; 2026-04-20..2026-10-07 | Session building a capability, for its ceremony | LA_OPERATIONS_INDEX.md (184 lines) | Yes | how-to | Good when listed; 21 of 31 other runbooks absent from it (all advanced_intake_*, uc010_*, web_search_go_live, at_rest_encryption_ceremony, vm_lifecycle, ...). |
| security | Audits, capstone deck and explainers, egress machinery and activation records, DATA_MAP, guest parser and oracle provisioning, proofs of concept (PCR seal, trust root), supply-chain pinning, post_capstone threat models | 59 / 61; 2026-06-03..2026-07-30 | Security sessions | None | Yes (count 54 stale) | study / decision / measurement | Medium: descriptive names, no list; frontmatter 0 of 25. Egress state is read from default.toml and runbooks, not here (CLAUDE.md). |
| sprints | ACTIVE_SPRINT.md (4,000-byte live pointer, refreshed 2026-10-02: no named sprint open), templates, sprint_18 (6 files), sprint_19 (kickoff brief), trust-spine brief | 12 / 12; 2026-04-21..2026-10-07 | Merging session that changes sprint state | None (ACTIVE_SPRINT is the pointer) | Yes (names sprint_18 only) | state | ACTIVE_SPRINT.md is the single live entry. |
| upstream | OpenVINO upstream contribution working sets and GPU-from-source build plan | 17 / 17; 2026-07-05..2026-09-22 | Upstream-contribution sessions | README in 725_xgrammar_stop_token only | Yes (count 10 stale) | study / how-to | Ticket-number folder names. |
| validation | exercises/ (one json) | 1 / 1; 2026-08-07 | One-off | None | NO | measurement | n/a |

INDEX names folders no longer in the tree: claude_projects, claude_cowork, scheduled. A repo-root reports/ shell (corrective_actions, task_28) is empty and untracked.

## 4. Other knowledge-bearing places outside docs/

| Place | Holds | Size / dates | Writer | Index | In docs/INDEX.md |
|---|---|---|---|---|---|
| .claude/rules/ (coding, doctrine, handoff, journal, performance, testing, vikunja) | Path-scoped doctrine delivered when a matching path is touched | 7 files, 139 lines | Doctrine changes via feature branch (doctrine.md) | CLAUDE.md <rules_index>; generated docs/governance/rules-corpus.yaml | No |
| .claude/agents (4), .claude/commands (3) | Agent definitions (adversarial-reviewer, dod-witness, hf-dataset-publisher, instrument-forensics) and sprint skills | 7 files | Doctrine author | None | No |
| evals/ | Model-quality eval harness (#717): suites, golden sets, committed baselines, battery, injection corpus | 69 tracked / 105 on disk; 6 md; last commit 2026-10-04 | Eval-running sessions | evals/README.md plus battery, dev, fixtures READMEs | No |
| phase2_gates/ | Frozen Phase-2 gate evidence, UAT summaries, OpenVINO issue 34450 draft comments and repro matrix | 209 tracked; 28 md; last commit 2026-07-09 | Closed | READMEs in two subfolders | No |
| tools/, scripts/ | Probes, measure, gate and doc-hygiene scripts; docs: tools/doc_lint/README.md, tools/perf_contrib/CONTRIBUTION_GUIDE.md, scripts/live_proof/README.md | 93 and 158 tracked | - | READMEs only | No |
| tests/ | Test code; tests/harness/README.md; tests/security/test_doctrine_freshness.py gates doc budgets | 250 tracked | - | One README | No |
| openvino/ (54,974 on-disk files), optimum-intel/ (203), models/ (3 tracked), requirements/ (3) | Third-party source clones, weights, dependency pins | untracked or ignored | - | - | No |

## 5. Knowledge KINDS and the single home for each (rule text quoted)

| Kind | Single home | Rule (source file) |
|---|---|---|
| Current project state | CLAUDE.md status_snapshot | "Volatile state lives ONLY in <status_snapshot>, refreshed at merge clusters and replaced (not appended)." (.claude/rules/doctrine.md) |
| Order of work | docs/ROADMAP.md | "docs/ROADMAP.md - THE ORDER." (CLAUDE.md live_state_pointers) |
| Task / work queue | Vikunja | "Vikunja is the task SSOT" (docs/INDEX.md section 2); "living work-queue SSOT" (CLAUDE.md repo_constellation) |
| Governance or architecture decision | docs/adrs plus DECISION_REGISTER row | "Every meaningful governance decision = ADR + journal entry naming the trade-off + DECISION_REGISTER.md row IN THE SAME CHANGE." (CLAUDE.md journal_discipline) |
| Technical decision | The causing Vikunja ticket | "Decisions recorded on the ticket that caused them - no standalone decision tickets." (.claude/rules/vikunja.md) |
| Narrative and reasoning of a ship | BUILD_JOURNAL.md, then docs/archive/journal/ | "BUILD_JOURNAL.md (narrative - HOT = current month only; prior months live verbatim in docs/archive/journal/ volumes + one-line INDEX)" (.claude/rules/journal.md); parallel sessions use docs/journal_fragments/ |
| Transferable lesson | LESSONS.md (full text LESSONS_ARCHIVE.md) | "transferable judgment -> the lesson"; "search LESSONS.md's hot index + Canonical Tier before minting a number" (journal.md) |
| Mechanical gotcha | FIELD_NOTES.md | "Mechanics -> FIELD_NOTES.md" (journal.md) |
| Measurement | PERFORMANCE_LOG.md plus docs/performance/ JSON | "dated narrative entry in PERFORMANCE_LOG.md + machine-readable JSON in docs/performance/" (.claude/rules/performance.md) |
| Milestone ledger | docs/ledger/ | "do not append anywhere but docs/ledger/" (docs/INDEX.md) |
| Review or audit finding outcomes | docs/reviews/<topic>-disposition-<date>.md | "Any review/audit/verification pass that returns findings gets a DISPOSITION RECORD" (CLAUDE.md deferral_discipline) |
| Incident stories behind rules | docs/governance/agent-doctrine-evidence.md | "Incident stories and dates go to docs/governance/agent-doctrine-evidence.md" (doctrine.md) |
| Operator procedures and ceremonies | docs/runbooks/ | "Authoritative LA runbooks live in docs/runbooks/" (docs/INDEX.md) |
| Live vs dormant runtime flags | services/assistant_orchestrator/config/default.toml | "LIVE vs DORMANT is read from config, never from memory." (CLAUDE.md) |
| Test policy and gate baseline | docs/TEST_GOVERNANCE.md | testing.md ssot attribute; CLAUDE.md live_state_pointers |
| Coder capability status | docs/design/CODER_DEFINITION_OF_DONE.md | "Statuses change only by MEASUREMENT." (CLAUDE.md) |
| Session handoff | docs/handoffs/ (git-ignored) | .claude/rules/handoff.md; template docs/governance/handoff-brief-template.md |
| Document lifecycle states | docs/governance/doc-lifecycle.md | "the four-part frontmatter every governed doc carries, the five lifecycle states it can be in" (doc-lifecycle.md) |
| Rule register | CLAUDE.md and .claude/rules/*, mirrored by docs/governance/rules-corpus.yaml | "Each rule has one home, CLAUDE.md or one of these files; docs/governance/rules-corpus.yaml records which." (CLAUDE.md rules_index) |
| Studies and research | docs/research (design-only), docs/reference (frozen), docs/security (security studies) | No single governing rule found. Gap. |

## 6. Folders and files with NO index

- Whole folders: adrs (only via DECISION_REGISTER), design, research (top level), reviews, security, reports, upstream, performance (top level), evidence, quality, validation, battery, demo, blairproweb, learning (top level), handoffs.
- Partial: runbooks (21 missing from LA index), DECISION_REGISTER (8 ADRs missing), docs/INDEX.md (5 folders absent, counts stale for about 14), archive (no index for ledger, lessons, platform_separation, testing).
- Long files with no topic index: PERFORMANCE_LOG.md (4947 lines), FIELD_NOTES.md (1478), BUILD_JOURNAL_ANTHOLOGY.md (3564), Use Cases_FINAL.md (610), LESSONS_ARCHIVE.md (777).
- Off-git and unindexed: root research PDFs, Intel Whitepapers, Temp Files, userdata, docs/handoffs, the stray docs/*.xml.

## 7. Orphans and duplicated knowledge

- Gate figure: CLAUDE.md snapshot and TEST_GOVERNANCE section 1; tests/security/test_doctrine_freshness.py forces them equal (controlled duplicate).
- Two decision registers: docs/DECISION_REGISTER.md and C:/Users/mrbla/devplatform/docs/DECISION_REGISTER.md (memory note: DEC-11 resolves two ways, #980).
- DECISION_REGISTER rows DEC-01 to DEC-08 cite docs/P5_TASK4_PRODUCTION_CONFIG_FEASIBILITY.md, which is no longer there (now docs/archive/2026/phase5-prompts/); DEC-09 cites docs/POST_OPERATIONAL_MATURATION_LEDGER.md, now a stub.
- Ledger: stub at docs/POST_OPERATIONAL_MATURATION_LEDGER.md, frozen monolith in docs/archive/ledger/, live docs/ledger/.
- Journal: BUILD_JOURNAL.md (current month), docs/archive/journal/ (history), docs/BUILD_JOURNAL_ANTHOLOGY.md (64 curated copies), docs/journal_fragments/ (pending).
- Lessons: LESSONS.md, LESSONS_ARCHIVE.md, docs/learning/lessons_deck (decks restating lessons).
- Performance: PERFORMANCE_LOG.md, docs/performance/*.json, docs/performance/community_export/ (re-exports and dataset card), the Hugging Face dataset; containment measurements also under docs/research/containment-evidence-2026-10-05/ and docs/performance/containment_probe_2026-10-10/.
- docs/INDEX.md section 1 lists the AI Risk Assessment, Critical Design Review and Phase_2_Test_Plan as repo-root files; they are in docs/reference/ (INDEX section 4 says so). Contradiction inside one file.
- Orphans from every index: docs/blairproweb, evidence, quality, validation; MODEL_EVALUATION_GEMMA4_12B and STANDARDS_Conformance_Audit; the 21 runbooks above; the 6 untracked docs/ stray files.
- Count rot, INDEX section 3 vs measured: adrs 34/46, runbooks 23/32, governance 17/45, research 16/298, security 54/59, performance 140/741, journal_fragments 6/27, guide-workstreams 18/37, upstream 10/17, archive ~700/583.

## 8. Vikunja as a knowledge store (not queried)

Per CLAUDE.md and .claude/rules/vikunja.md the board holds what the repo deliberately does not: the live work queue and task state (Active, Blocked, Complete labels); ticket descriptions as the authority on what work is (comments are history); dated "CURRENT STATE" comments (built vs remaining, evidence); technical decisions made on the ticket that caused them; "DEAD END: tried X, failed because Y" notes; deferral records with blocked-by predicates; closing comments citing shipping SHAs; unblock comments on dependent tickets; the LA decision queue. The repo carries only ticket numbers: 181 tracked docs files start with a 3-4 digit ticket number, and commit subjects cite them. There is no ticket-to-document index; the link is by number only. The server binary lives under C:/Users/mrbla/devplatform. Not verified: ticket counts, label usage, comment volume (no Vikunja calls made).

## 9. Not verified

- Vikunja contents and counts.
- Whether git-ignored files are meant to be kept (treated as present and unindexed).
- Topic coverage per file; find-by-topic notes judge structure only (indexes, headings, frontmatter, filenames).
- Dates are git first-add to last commit; for evals, tools, scripts only counts and last commit were measured. Handoffs dates are filesystem mtimes. Frontmatter percentages count tracked .md files whose first line is "---".
