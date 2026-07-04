# Active Sprint — BlarAI

> **Purpose**: One-stop human-friendly pointer to the currently-active sprint's artifacts. Auto-maintained by Co-Lead Architect Phase 3 on every sprint transition. Do **not** hand-edit — Co-Lead overwrites on the next transition.
>
> **Source of truth**: `docs/active_tasks.yaml` (the machine-readable roster). This file is a derived human view.
>
> **Last refresh (2026-06-07)**: **Sprint 16 CLOSED — COMPLETE** (9/9 SDV criteria MET; independent SWAGR `STRONG_ALIGNMENT`, 0 CRITICAL / 0 MAJOR / 5 MINOR all dispositioned). 7 worktree streams merged under the serial gate; Layer-A 2172→2187. Two deliverables (D real-GPU boot-smoke #619, A GUI tiers #621) ship BUILT+SCRIPTED with green runs deferred to the Sprint-17 kickoff; #106/FUT-04 PARTIAL. Artifacts under `docs/sprints/sprint_16/` (SDV v2 / SCR / SWAGR) + ledger `docs/ledger/20260607_133305_sprint16_scr_automation-wave.md`. No sprint currently active — the next kickoff (Sprint 17, the Boot Cluster; needs the egress-policy decision) is the LA's. **Currency note:** the full active-block + historic-table restructure (moving Sprint 15 + 16 into the historic table) is done by the Sprint-17 kickoff per this file's auto-maintain-at-transition protocol; the Sprint-15 detail block below is retained until then.

---

## Currently active

> **✅ SPRINT 16 CLOSED — COMPLETE (2026-06-07).** "The Automation Wave" (Vikunja #624). 9/9 SDV criteria MET; independent SWAGR `STRONG_ALIGNMENT`, 0 CRITICAL / 0 MAJOR / 5 MINOR (all dispositioned at close). 7 worktree streams merged under the serial merge gate; Layer-A 2172→2187 (+ the #619 lane 18 passed). Two deliverables ship BUILT+SCRIPTED with green runs **deferred to the Sprint-17 kickoff dev-machine session** (D real-GPU boot-smoke #619, A GUI tiers #621 — committed ≠ done until green); **#106/FUT-04 PARTIAL** (signed-manifest mechanism staged default-OFF; ceremony runbooked). Artifacts: SCR + SWAGR under `docs/sprints/sprint_16/`; ledger `docs/ledger/20260607_133305_sprint16_scr_automation-wave.md`. **No sprint is currently active** — the next kickoff (Sprint 17, the Boot Cluster: #615 → egress → the full production boot integration test; needs the egress-policy LA decision) is the LA's. *(The Sprint-15 detail block below + the historic-table move are reconciled at the Sprint-17 kickoff per the auto-maintain-at-transition protocol; Sprint 15 itself CLOSED COMPLETE 2026-06-07, 8/8 MET.)*

**Sprint 15 — Tier-2 production-posture: per-boot mTLS + dev-mode-off flip (fidelity-2).** Tracking task **#616** (`Gate:Approved` → CLOSED 2026-06-07). SDV **v4 signed off** by the LA 2026-06-06.

### Artifacts

| Artifact | Path | Status |
|---|---|---|
| **Strategic Design Vision (SDV)** | [docs/sprints/sprint_15/strategic_design_vision.md](sprint_15/strategic_design_vision.md) | ✅ **Signed v4** 2026-06-06 (flip-timing locked: mechanism EA-2 / activation EA-4); v2/v3 superseded |
| **Strategic Completion Report (SCR)** | [docs/sprints/sprint_15/strategic_completion_report.md](sprint_15/strategic_completion_report.md) | ✅ **Authored 2026-06-07** (v1; §9 post-SWAGR reconciliation complete — 8/8 MET) |
| **SWAGR** | [docs/sprints/sprint_15/Strategic_Work_Analysis_and_Gap_Report_Sprint_15_20260607_094439.md](sprint_15/Strategic_Work_Analysis_and_Gap_Report_Sprint_15_20260607_094439.md) | ✅ **Landed `423167e`** — STRONG_ALIGNMENT, 8/8 MET, 0 CRITICAL / 0 MAJOR / 6 MINOR |
| **EA prompts** | `docs/sprints/sprint_15/ea_prompts/` | **EA-1/2/3 + EA-4a/b/c/d/e/f ALL MERGED.** Flip ACTIVATED (EA-4b `e1858a5`; production is the HOST default). **EA-4 production live-verify IN PROGRESS** (LA on-chip). Boot-1 has cleared **7 production-only gaps** the dev-default had masked: (1) cryptography-not-in-bare-python, (2) wrong cwd, (3) AF_HYPERV proto WinError 10041 (EA-4c), (4) host-mode loopback+mTLS transport — AF_HYPERV deferred #615 (EA-4d), (5) orch cert + (6) router cert mint (EA-4e), (7) PA HANDSHAKE_REQUEST handler (EA-4f). **Boot-1 reached the app window** — production cascade passed (signing live, per-boot mTLS handshake on the freshly-minted CA, no dev fallback). One block remains: `list_sessions` raises on **dev-era practice sessions** in `sessions.db` (encrypted under the old dev SoftwareSealer key `sessions.keystore.json`; the now-active production TPM DEK `dek_keystore.json` correctly refuses them — InvalidTag on `7308bf05…` tonight, `034be448…` pre-flip). Store init + the production DEK are healthy/stable (DEK keystore unchanged since 6/5 21:43 across all tonight's boots); only the read of legacy rows fails, and Sprint-14's deliberately-locked all-or-nothing fail-closed (`test_wrong_key_on_existing_db_fails`) turns that one bad row into an app-wide "backend not running" (cid=d2044880). **RESOLVED — fix merged across BOTH encrypted stores (#618; orchestrator merge-gate, re-verified): session store `4af2033` (105 tests) + substrate store `6fe1fcc` (63 tests).** Corrected as a defect (not a posture decision — confidentiality/integrity unchanged, plaintext never returned): the bulk readers in both stores (session `list_sessions`/`get_session_turns`/`_backfill_empty_titles`; substrate `_load_embed_cache`/`_search_kind`) now **quarantine** an un-decryptable row (omit + emit a `*_ROW_DECRYPT_QUARANTINE` WARNING) instead of letting one bad row brick the store / AO startup; single-record + write paths keep hard fail-closed (ADR-025 §2.7 + Sprint-14 SDV §3 amendments). **Resume:** a plain re-boot now serves — the practice-era rows are auto-quarantined; **no data-dir action needed**. Runbook: [EA4_ceremony_runbook.md](sprint_15/EA4_ceremony_runbook.md). **(2) Next production gap — prompt routing (#620, `ecbd991`):** boot reached the app but rejected every prompt (`Unsupported message type: PROMPT_REQUEST`) — the launcher wired the gateway to the PA (5000) not the Orchestrator (5001) in prod host-mode (fixed: `resolve_gateway_port` single-source-of-truth, regression-locked vs the AO config; the model-loaded prompt-flow preflight is now **default-ON in prod** so the boot self-verifies the full `send_prompt→AO→stream` path fail-closed before the UI). **BOOT-1 LIVE-VERIFY PASSED — LA-confirmed 2026-06-06:** prompts respond, paperclip→photo→model describes it correctly, Qwen3-VL evicts from RAM after the prompt. **Remaining:** 2nd-boot continuity (plain re-boot stays clean) → Sprint-15 close (fold the 12 `docs/journal_fragments/2026-06-*` into BUILD_JOURNAL; SCR; SWAGR; ledger; #616 close). |

**Scope:** build per-boot mTLS certificate generation for the vsock channel (+ new ADR-026), flip dev-mode OFF (activating the dormant audit-TPM + JWT signing from Sprint 14), verify host-local at production posture (**fidelity-2**), and run one LA on-chip ceremony + production live-verify. EA-1 (cert gen) → EA-2 (flip) [sequential — shared launcher file] → EA-3 (cascade + stub harness) → EA-4 (ceremony + live-verify).

**Three gate-honesty conditions (LA):** (1) the guest↔host AF_HYPERV boundary handshake is deferred + tracked **#615**; (2) fidelity-2 claims only the host-local machinery; (3) the staged manifest is minimal-for-boot, full FUT-04 stays tracked **#106**.

**Campaign status:** the air-gap **stays up**; **#598 remains the GO/NO-GO gate**. After Sprint 15, remaining gate-critical work = the deferred guest-boundary handshake (#615), full FUT-04 weight integrity (#106), egress per-action mediation + exfil-screen + kill-switch for web tools (Tier-3), and the capstone security presentation (#612, closing bookend). *(The Cleaner / UC-003 was removed from THIS roadmap to a separate/future project — LA 2026-06-06, #613; was previously a post-#598 fast-follow.)*

---

## Historic sprints (completed)

| Sprint | Name | Completed | SDV | SCR | SWAGR | Final merge on main |
|---|---|---|---|---|---|---|
| `14` | Tier-2 at-rest encryption + audit-stream TPM signing | 2026-06-06 | [✅ v3](sprint_14/strategic_design_vision.md) | [✅ v1](sprint_14/strategic_completion_report.md) | [✅ 20260605_swagr](sprint_14/Strategic_Work_Analysis_and_Gap_Report_Sprint_14_20260605_swagr.md) | `e08a7db` (#609; EA-1..EA-9 + #605 audit signer; orchestrator merge-gate; encryption live-verified) |
| `13` | Tier-1 security finishers | 2026-06-05 | [✅ v1](sprint_13/strategic_design_vision.md) | [✅ v1](sprint_13/strategic_completion_report.md) | [✅ 20260605_205834](sprint_13/Strategic_Work_Analysis_and_Gap_Report_Sprint_13_20260605_205834.md) | `a8284d1` (#602 audit stream; orchestrator merge-gate, 2 rounds) |
| `12` | Provenance- and intent-aware content handling | 2026-06-05 | [✅ v4](sprint_12/strategic_design_vision.md) | [✅ v1](sprint_12/strategic_completion_report.md) | [✅ 20260605_061513](sprint_12/Strategic_Work_Analysis_and_Gap_Report_Sprint_12_20260605_061513.md) | `90b2bed` (#591 capability-scoped locking; direct-to-main per Q3-B) |
| `11` | Process-Hygiene Backlog Paydown | 2026-05-12 | [✅ v3](sprint_11/strategic_design_vision.md) | [✅ v1](sprint_11/strategic_completion_report.md) | ⏳ Pending Sprint Auditor cadence | `50af4a0` (EA-5 cleanup batch via Co-Lead direct merge under LA-delegated authority) |
| `10` | Doctrine Split | 2026-05-11 | [✅ v1](sprint_10/strategic_design_vision.md) | [✅ v1](sprint_10/strategic_completion_report.md) | [✅ 20260511_171900](sprint_10/Strategic_Work_Analysis_and_Gap_Report_Sprint_10_20260511_171900.md) | `9e5555c` (EA-3 devplatform doctrine authorship + SOP portability fix) |
| `9` | Governance Documentation | 2026-04-24 | [✅ v1](sprint_9/strategic_design_vision.md) | [✅ v1](sprint_9/strategic_completion_report.md) | [✅ 20260424_053153](sprint_9/Strategic_Work_Analysis_and_Gap_Report_Sprint_9_20260424_053153.md) | `2e077af` (EA-5 governance landing page) |
| `8` | Test Quality Remediation | 2026-04-23 | [✅ v2](sprint_8/strategic_design_vision.md) | [✅ v1](sprint_8/strategic_completion_report.md) | [✅ 20260424_051646](sprint_8/Strategic_Work_Analysis_and_Gap_Report_Sprint_8_20260424_051646.md) | `b83a870` (EA-5 via `la_merge_approve`) |
| `7` | Audit Test Suite | 2026-04-21 | ❌ Pre-DEC-15 (not authored) | ❌ No SDV baseline | ❌ No SCR | `46278a9` (EA-5 synthesis) |

---

## Sprint 11 — detail (completed)

### Artifacts

| Artifact | Path | Status |
|---|---|---|
| **Strategic Design Vision (SDV)** | [docs/sprints/sprint_11/strategic_design_vision.md](sprint_11/strategic_design_vision.md) | ✅ Signed 2026-05-11 (v1) → v2 (parallel authorization) → v3 (cross-reference symmetric expansion) |
| **Strategic Completion Report (SCR)** | [docs/sprints/sprint_11/strategic_completion_report.md](sprint_11/strategic_completion_report.md) | ✅ Authored 2026-05-12 — Co-Lead Phase 3 |
| **Strategic Work Analysis & Gap Report (SWAGR)** | `docs/sprints/sprint_11/Strategic_Work_Analysis_*.md` | ⏳ Pending Sprint Auditor cadence |
| **SDO continuation XML** | `docs/P5_TASK11_SDO_CONTINUATION_v1.0.xml` | ✅ Authored 2026-05-11 |
| **EA prompts (archived)** | `docs/scheduled/ea_queue/archive/sprint_11/` | All 5 EA queue files archived post-merge |
| **Milestone reports (DEC-13)** | `docs/sprints/sprint_11/reports/` | Accumulated during execution |
| **Test-baseline drift investigation (EA-4)** | [docs/sprints/sprint_11/test_baseline_drift_investigation.md](sprint_11/test_baseline_drift_investigation.md) | ✅ Authored 2026-05-12 — verdict BENIGN environmental drift |

### EA milestones — final status

| EA-# | Scope (short) | Status | Merge commit |
|---|---|---|---|
| EA-1 | DEC bundle (DEC-16/17/18) — devplatform | ✅ Merged | `be09999` (BlarAI ledger) + `0dbd4a6` (devplatform DECs) |
| EA-2 | Active State refresh procedure + Co-Lead wake-template hook | ✅ Merged | `cf95e4b` (BlarAI) + `674a0a9` (devplatform hook) |
| EA-3 | SWAGR template §5.4 cross-repo + SDV §8.4 pointer fix | ✅ Merged | `9464346` |
| EA-4 | Test-baseline drift investigation report | ✅ Merged (Co-Lead direct execution under LA-delegated authority) | `3b4b645` |
| EA-5 | Doctrine + doc-hygiene cleanup batch (cross-repo) + DEC-19 | ✅ Merged (Co-Lead direct execution under LA-delegated authority) | `50af4a0` (BlarAI) + `2b06d79` (devplatform) |

### Sprint 11 SCR §14.1 carry-overs

Two fleet-mechanism bugs surfaced during EA-4 dispatch; both are HIGH-priority Sprint 12 candidate items:

| Carry-over | Description | Sprint 12 candidate work |
|---|---|---|
| 1 | Within-sprint parallel EA + multi-EA-on-same-tracking-task state-machine misclassification | Add `ea_number` disambiguation to EA Code wake-template state-machine OR adopt per-EA tracking sub-tasks for parallel windows |
| 2 | Vikunja label-revert phenomenon on tracking task #410 (six independent SDO writes reverted within \~5 min) | Identify the reverter agent or hook; scope-correct or disable |

Plus the Sprint 12+ baseline-string convention recommendation from EA-4 §6: adopt `{commit, environment, date}` triple instead of raw count.

---

## Sprint 10 — detail (completed)

### Artifacts

| Artifact | Path | Status |
|---|---|---|
| **Strategic Design Vision (SDV)** | [docs/sprints/sprint_10/strategic_design_vision.md](sprint_10/strategic_design_vision.md) | ✅ Signed 2026-05-09 |
| **Strategic Completion Report (SCR)** | [docs/sprints/sprint_10/strategic_completion_report.md](sprint_10/strategic_completion_report.md) | ✅ Authored 2026-05-11 — commit `90db41f` |
| **Strategic Work Analysis & Gap Report (SWAGR)** | [docs/sprints/sprint_10/Strategic_Work_Analysis_and_Gap_Report_Sprint_10_20260511_171900.md](sprint_10/Strategic_Work_Analysis_and_Gap_Report_Sprint_10_20260511_171900.md) | ✅ Landed `14ac80d` |
| **SDO continuation XML** | [docs/P5_TASK10_SDO_CONTINUATION_v1.0.xml](../P5_TASK10_SDO_CONTINUATION_v1.0.xml) | ✅ Authored 2026-05-09 |
| **EA prompts (archived)** | `docs/scheduled/ea_queue/archive/sprint_10/` | All 3 EAs archived post-merge |
| **Milestone reports (DEC-13)** | `docs/sprints/sprint_10/reports/` | Accumulated during execution |
| **Doctrine Classification Matrix (EA-1 deliverable)** | [docs/sprints/sprint_10/doctrine_classification_matrix.md](sprint_10/doctrine_classification_matrix.md) | ✅ Authored 2026-05-11 (EA-1) |

### EA milestones — final status

| EA-# | Scope (short) | Status | Merge commit |
|---|---|---|---|
| EA-1 | Doctrine Classification Matrix (audit-only) | ✅ Merged via `la_merge_approve` | `caa46f5` |
| EA-2 | BlarAI Strip + Active State Refresh + AGENTS.md Pointer | ✅ Merged via `la_merge_approve` | `1b1614e` |
| EA-3 | devplatform Doctrine Authorship + SOP Portability Fix | ✅ Merged direct-to-main (devplatform side `9e5555c`; BlarAI metadata `4b2dfa0`) | (cross-repo) |

### Sprint 10 verdict + carry-overs

SWAGR verdict: `ACCEPTABLE_ALIGNMENT` / `INCREMENTAL` / `IMPROVED`. 7/7 SDV criteria PASS, 0 CRITICAL / 0 MAJOR / 6 MINOR. All six MINOR gaps rolled into Sprint 11 scope:

| Sprint 10 SWAGR gap | Sprint 11 EA |
|---|---|
| #1 Active State baseline drift (\~981 vs live 1001) | EA-2 + EA-4 |
| #2 copilot-instructions.md:93 narrative DEC-15 reference | EA-5 |
| #3 Cross-reference style asymmetry BlarAI vs devplatform | EA-5 |
| #4 SOP verification path (transparent; no action) | — (acknowledged, no Sprint 11 action) |
| #5 Sprint-close-comment audit path | EA-5 (Sprint Auditor wake-template §2.2 amendment) |
| #6 SWAGR template cross-repo §5.4 amendment | EA-3 |

---

## Sprint 9 — detail (completed)

### Artifacts

| Artifact | Path | Status |
|---|---|---|
| **Strategic Design Vision (SDV)** | [docs/sprints/sprint_9/strategic_design_vision.md](sprint_9/strategic_design_vision.md) | ✅ Signed 2026-04-22 |
| **Strategic Completion Report (SCR)** | [docs/sprints/sprint_9/strategic_completion_report.md](sprint_9/strategic_completion_report.md) | ✅ Authored 2026-04-24 — commit `488602b` |
| **Strategic Work Analysis & Gap Report (SWAGR)** | [docs/sprints/sprint_9/Strategic_Work_Analysis_and_Gap_Report_Sprint_9_20260424_053153.md](sprint_9/Strategic_Work_Analysis_and_Gap_Report_Sprint_9_20260424_053153.md) | ✅ Landed `d9a5ac1` |
| **SDO continuation XML** | [docs/P5_TASK9_SDO_CONTINUATION_v1.0.xml](../P5_TASK9_SDO_CONTINUATION_v1.0.xml) | ✅ Authored 2026-04-22 |
| **EA prompts (archived)** | `docs/scheduled/ea_queue/archive/sprint_9/` | All 5 EAs archived post-merge |
| **Milestone reports (DEC-13)** | `docs/sprints/sprint_9/reports/` | Accumulated during execution |

### EA milestones — final status

| EA-# | Scope (short) | Status | Merge commit |
|---|---|---|---|
| EA-1 | Security Boundary & Wire Protocol (GOV-04, GOV-02, GOV-03) | ✅ Merged | `ef670eb` |
| EA-2 | Runtime Behavior & Resilience (GOV-05, GOV-06, GOV-07) | ✅ Merged | `9f7a6d6` |
| EA-3 | Operational State (GOV-08, GOV-09, GOV-11) | ✅ Merged | `d26a111` |
| EA-4 | Ops, Deployment, Rule Engine (GOV-12, GOV-13, GOV-14) | ✅ Merged | `e49f788` |
| EA-5 | Governance Landing Page (README synthesis) | ✅ Merged | `2e077af` |

---

## Sprint 8 — detail (completed)

### Artifacts

| Artifact | Path | Status |
|---|---|---|
| **Strategic Design Vision (SDV)** | [docs/sprints/sprint_8/strategic_design_vision.md](sprint_8/strategic_design_vision.md) | ✅ Signed 2026-04-22 (v2 applied) |
| **Strategic Completion Report (SCR)** | [docs/sprints/sprint_8/strategic_completion_report.md](sprint_8/strategic_completion_report.md) | ✅ Authored 2026-04-24 — commit `117142b` |
| **Strategic Work Analysis & Gap Report (SWAGR)** | [docs/sprints/sprint_8/Strategic_Work_Analysis_and_Gap_Report_Sprint_8_20260424_051646.md](sprint_8/Strategic_Work_Analysis_and_Gap_Report_Sprint_8_20260424_051646.md) | ✅ Landed `b8204c4` |
| **SDO continuation XML** | [docs/P5_TASK8_SDO_CONTINUATION_v1.0.xml](../P5_TASK8_SDO_CONTINUATION_v1.0.xml) | ✅ Authored 2026-04-22 |
| **EA prompts (archived)** | `docs/scheduled/ea_queue/archive/sprint_8/` | All 5 EAs archived post-merge (including the retroactive EA-5 orphan archival `P5_TASK8_EA5_STRUCTURAL_CLEANUP_executed_20260423_b83a870.xml`) |
| **Milestone reports (DEC-13)** | `docs/sprints/sprint_8/reports/` | Accumulated during execution |

### EA milestones — final status

| EA-# | Scope (short) | Status | Merge commit |
|---|---|---|---|
| EA-1 | Policy Agent test hardening (+22 tests) | ✅ Merged | `b85be4c` |
| EA-2 | AO + Semantic Router (PGOV, dual-gate, all 13 AO config constraints) | ✅ Merged | `0b5e5ec` |
| EA-3 | UI Gateway + UI Shell (+65 tests) | ✅ Merged | `12fd0ba` |
| EA-4 | Shared + Launcher + Integration (+46 tests) | ✅ Merged | `3563257` |
| EA-5 | Cross-service structural cleanup (NPU→GPU, 23 live-TCP moves) | ✅ Merged via `la_merge_approve` | `b83a870` |

### Sprint 8 SWAGR gap closure (Sprint-9-window cleanup)

All actionable Sprint 8 SWAGR gaps addressed during the Sprint-9 / post-Sprint-9 maintenance window:

| Gap | Fix |
|---|---|
| #1 MAJOR: EA-1 ledger stranded in frozen monolithic | Bridging stub at `docs/ledger/20260422_044000_sprint8_ea1_policy-agent-hardening.md` |
| #3 MINOR: no DEC for Q1-1 ledger / diff-size / parallel-sprint | `docs/governance/merge-policy.md` + `docs/governance/parallel-sprints.md` |
| #5 MINOR: CLAUDE.md Active State stale | Refreshed |
| #6 MINOR: parallel-sprint shared-artifact audit | SDV template §8.4 + `docs/governance/parallel-sprints.md` + `parallel_sprints_authorized` flag with auto-clear |
| #7 MINOR: pytest unverifiable in auditor env | Added to Sprint Auditor allowed_tools + wake template Phase 2 step 3 |

---

## Sprint 7 — detail (completed)

### Artifacts

| Artifact | Path | Status |
|---|---|---|
| **Strategic Design Vision (SDV)** | `docs/sprints/sprint_7/strategic_design_vision.md` | ❌ Not authored — Sprint 7 predates DEC-15; backfill declined per LA direction |
| **Strategic Completion Report (SCR)** | `docs/sprints/sprint_7/strategic_completion_report.md` | ❌ Not authored — no SDV baseline to measure against |
| **Strategic Work Analysis & Gap Report (SWAGR)** | `docs/sprints/sprint_7/Strategic_Work_Analysis_*.md` | ❌ Not scheduled — no SCR to audit |
| **SDO continuation XML** | [docs/P5_TASK7_SDO_CONTINUATION_v1.0.xml](../P5_TASK7_SDO_CONTINUATION_v1.0.xml) | ✅ Authored 2026-04-21 |
| **EA prompts** | `docs/scheduled/ea_queue/archive/sprint_7/` | All 5 EAs complete |
| **Milestone reports (DEC-13)** | `docs/reports/task_28/` (legacy path — Sprint 7 pre-DEC-15) | 10 reports accumulated |

### EA milestones — final status

| EA-# | Scope (short) | Status | Commit |
|---|---|---|---|
| EA-1 | Policy Agent + Assistant Orchestrator audit | ✅ Merged | (pre-session) |
| EA-2 | Semantic Router audit | ✅ Merged | (pre-session) |
| EA-3 | UI Gateway + UI Shell audit | ✅ Merged | `6cc2463` |
| EA-4 | Shared + Launcher + Integration audit | ✅ Merged | rollup `1f4aa20` |
| EA-5 | Synthesis — Sections 5 + 6 (Gap Report + Skip Analysis) | ✅ Merged | `46278a9` |

---

## How to use this file

### As the LA

- Open this file any time you want to know "what's the fleet doing right now at the strategic level?"
- **Currently**: no sprint active — Sprint 14 closed 2026-06-06 (COMPLETE + live-verified). The next kickoff is the LA's.
- Historic sprints table is a jumpable archive.

### From Claude Desktop / Claude Code (interactive)

- *"What's the active sprint?"* → Claude reads this file and `active_tasks.yaml`.
- *"What did Sprint 8 accomplish?"* → See Sprint 8 detail section above + linked SCR/SWAGR.

### From scheduled agents

- Scheduled agents use `docs/active_tasks.yaml` as authoritative. This pointer is for human convenience.

---

## Protocol: who writes what, when

| Event | Writer | Trigger |
|---|---|---|
| Sprint transition | Co-Lead Phase 3 Step 0 | `active_tasks.mark_task_complete(predecessor)` |
| LA mid-sprint amendment (e.g., scope change) | LA hand-edits, then commits | LA discretion — but prefer amending the SDV instead of this pointer |
| Backfill historic sprint row | Co-Lead or manual | Historic completeness pass |

---

## See also

- [CLAUDE.md § Current Active Sprint (DEC-15)](../../CLAUDE.md#current-active-sprint-dec-15)
- [docs/DEC15_SPRINT_STRATEGIC_REVIEW_PROPOSAL_v1.xml](../DEC15_SPRINT_STRATEGIC_REVIEW_PROPOSAL_v1.xml)
- [docs/governance/parallel-sprints.md](../governance/parallel-sprints.md)
- [docs/governance/merge-policy.md](../governance/merge-policy.md)
- [docs/sprints/_templates/](_templates/)
- [docs/active_tasks.yaml](../active_tasks.yaml)
