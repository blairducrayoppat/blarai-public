---
title: BlarAI Knowledge Map, topic cards batch 3
status: living
area: research
---

# Knowledge Map batch 3: four topic cards

Drafted 2026-10-11 from the main checkout `C:/Users/mrbla/BlarAI`. Read-only: no repository edit, no git, no Vikunja call. Same schema as `docs/research/KNOWLEDGE_MAP.md` section 1: (a) question; (b) current answer and status; (c) evidence table; (d) layers of zoom; (e) open questions with the observable that closes each; (f) decisions made and waiting; (g) tickets; (h) raw sources. Acronyms are spelled out on first use inside each card. Grades: **M** measured on this machine; **S** read from source code or a primary artifact; **V** vendor documentation only; **R** reasoning or design. "Not verified" marks anything I could not check. Ticket text was NOT read (no Vikunja call); ticket numbers come from the cited files.

Direct checks I ran today (2026-10-11) and so grade **S/M**: `default.toml` flag values for dispatch, guest oracle, image generation and the coordinator (read); a listing of the LA's Desktop folder (M); a search of `shared/`, `services/`, `launcher/`, `tests/`, `tools/` for callers of the coordinator's boot canary and signed-policy functions (S); existence checks on every path cited here.

Cards in this batch (continuing the lettering of `KNOWLEDGE_MAP_BATCH2.md`):
- Card E: The coder fleet: capability, Definition of Done and the measurement problem
- Card F: Self-governance boundary, the Coordinator and supervised autonomy
- Card G: People-facing surface: UI, voice, images and the novice-operator design
- Card H: Measurement discipline and the evidence system

---

## Card E. The coder fleet: capability, Definition of Done and the measurement problem

### Summary (5 lines)
1. "The coder" is the headless coding fleet (use case UC-005 in `Use Cases_FINAL.md`): a plain-language goal becomes a plan, a local 30-billion-parameter model builds it in isolated workspaces, and deterministic checks plus a hidden test ("oracle") decide pass or park. The dispatch switch reads `enabled = true` (go-live 2026-06-27, ticket #670) in `services/assistant_orchestrator/config/default.toml`.
2. The target is written down: `docs/design/CODER_DEFINITION_OF_DONE.md` (DoD) holds 21 numbered capabilities and two acceptance tests. By its own status lines, 3 rows read LIVE (1, 3, 5), row 2 ARMED, row 6 split between stood-down and armed, and the other 16 PARTIAL. Both acceptance tests read "Executed: NEVER". Statuses change only by measurement.
3. The hard part is not building, it is knowing. The project repeatedly found its own graders reporting a pass they had not measured, and counted the same website attempts three different ways (section d). A success rate on card B9 depends on which denominator is used.
4. Order of work is `docs/ROADMAP.md` ("THE ORDER"). Its prose is dated mid-August; its machine-checked block is the part a script verifies. The LA decided 2026-08-15 that unfinished work carries on rather than restarts, and that Python-side probing is paused until the website side is on par.
5. Open and the LA's: his hands-on verdict of a built site (#1343), the bar on "requirements never checked", and an acceptable success rate. Not verified by me: any ticket's current state, any B9 count after 2026-08-30, and whether DoD row statuses have moved since their last dated line.

### (a) The question
What does a "working" local coder mean, how far away is it, which numbers about it can be trusted, and what decides what is worked on next?

### (b) Current answer and status
**Provisional; the definition is decided, the achievement is measured as partial.**
- *Decided* (LA, 2026-07-30 and 2026-08-06): the goal in his words is quoted at the top of the DoD (a reliable, secure coder for Python and multi-page websites with advanced intake and interview, a local corpus, and proper exams and reviewers; "we don't need to one-shot websites any more").
- *Decided* (LA, 2026-08-15, ROADMAP "What you have to decide"): carry on rather than restart when a run leaves work unfinished; the Python pause covers daytime probes and ends only by his explicit act (recorded on #1385).
- *Decided* (LA, DEC-14 in `docs/DECISION_REGISTER.md`): the nightly battery is cancelled indefinitely; no scheduled run, 23:00 gates nothing.
- *Read today*: `[fleet_dispatch]` `enabled = true` (default.toml line 435), `guest_oracle_enabled = true` (line 1066). The cross-model critic is described as dormant in `docs/research/heterogeneous-multimodel-dispatch-recommendation-2026-07.md` (2026-07-17); not re-read by me from config.
- *Open*: the LA queue named in `CLAUDE.md` status_snapshot (#1343 site verdict, #746, #929, #922, #1303). I did not read those tickets.
- Deciding documents: `docs/design/CODER_DEFINITION_OF_DONE.md` (the target), `docs/ROADMAP.md` (the order), `docs/adrs/ADR-035-Acceptance-Layer.md` and `docs/adrs/ADR-037-Grading-and-Integration-Machinery.md` (how work is judged), `docs/adrs/ADR-038-Candidate-Model-Evaluation-Protocol.md` (how a replacement model is judged).

### (c) Evidence table
| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-06-26 | `docs/research/dispatch-capability-and-leverage-assessment-2026-06.md` | The architecture's philosophy (deterministic gate as judge, model as signal) is right; the review side is saturated and best-of-N sampling with the gate as selector was the unpulled lever. | V + R | Citations inline; headline numbers said to be re-fetched from primary sources. |
| 2026-07-05 | `docs/research/fleet-maturation-program-plan-2026-07.md` (#740) | Chose the long-task coding fleet over a medical-portal agent as the capability to mature; draft v1.3 awaiting LA review at its date. | R | Status line is as of authoring; later status not verified. |
| 2026-07-17 | `docs/research/heterogeneous-multimodel-dispatch-recommendation-2026-07.md` | A four-model pipeline is not recommended: the dense 27B judge ran at 3.59 tokens per second, about 10 times slower than any mixture-of-experts model of its size on this Arc 140V. Consolidation onto the 35B-A3B was recommended instead. | M (speed) + R | The 35B consolidation rested on a swap gated by a verdict later retracted (lesson 369, Card H). |
| 2026-07-20 | `docs/research/evaluation-measurement-assessment-2026-07-20.md` | The standing gate measures model quality "essentially not at all" (all 41 model cases skipped); the hardware tier had no teeth; four defects found, all ticketed. | S | Five research legs, re-verified at source per its header. |
| 2026-07-21 | `docs/research/coder-capability-2026-07/coder-capability-assessment-2026-07-21.md` | Over 49 usable runs on 8 cards: B2 (text-stats CLI) green on every valid night over a 15-run history; web cards undetermined or harness-limited. Sandbox-scale apps, small samples, grader under repair. | M (archive) | Its own section 1 says it is not an external benchmark. |
| 2026-07-21 | `docs/research/ui-seam-and-task-grain-research-2026-07-21.md` | Assert at the page structure a user sees; bigger tasks along real seams beat many small ones. | V (cited literature) | Its honesty section names what could not be established. |
| 2026-07-24 | `docs/research/746-solve-rate-measurement-design-2026-07-24.md`, `746-validation-program-2026-07-24.md` | A naive before/after test of plan-time research grounding on the current cards would likely show nothing either way; a paired design is proposed. | R | Status "proposal" / "in-progress"; results not read. |
| 2026-07-24 | `docs/research/1101-fleet-import-surface-measurement-2026-07-24.md` | The fleet's generated code shows almost no real third-party Python use; skeletons are generated with `dependencies = []`. | M (200 run directories, 27 project directories per its method) | Structural property, not a sampling gap, per the file. |
| 2026-07-30 | `docs/research/coder-fleet-overhaul-program-2026-07-30.md` | Four gaps: the battery did not test merged code (#1181), controls keyed on strings can be silenced, exam coverage of requirements is unknown (every green was GREEN-UNVERIFIED), nothing asked whether code is secure (#1182). | S | Status "proposed"; some gaps since addressed (DoD row 3 LIVE for security). |
| 2026-08-14 | `docs/design/CODER_DOD_COMPLETION_MAP_2026-08-14.md` | A scoreboard classing each DoD row by gap type (absent, unwired, starved, needs-operator, stale); says fourteen rows misstate the repo in one direction or the other. | S (three measurement passes) | A snapshot; its own header says do not trust its numbers after a night runs. |
| 2026-08-14/15 | DoD row 21 text (`docs/design/CODER_DEFINITION_OF_DONE.md`, status line near line 2002) | Same 946-character goal, same plan, 11 completed runs under an explicit grouping rule: re-grading a fixed delivery is stable (0 of 30) but re-running is not. The "eight runs" table reads GREEN 1, PARKED-HONEST 5, STALLED 2; the file notes 17 under a looser reading. | S | The row itself records that its first tally stated no grouping rule. |
| 2026-08-15 | `docs/ROADMAP.md` ("Right now", "The critical path") | Measured 17 from-scratch attempts at one site oscillating, best result left in an archive; B9 "graded its stated goal once in eighteen attempts". | S | Prose dated 2026-08-15/17; the header says the block, not the prose, is verified. |
| 2026-10-04 | `docs/ROADMAP.md` header | `scripts/verify_roadmap.py` checked 21 rows against the board: 0 stale, 0 missing, 1 needs the operator. Prose claims were not re-verified, nothing re-ranked. | S | The date bump says exactly what it re-measured. |
| 2026-08-09 | DoD row 14 (`docs/design/CODER_DEFINITION_OF_DONE.md`) with `shared/instrument_registry.py` | 15 graders are registered with a required "proven to fail" pair (toggle, seam, quiet tests); the CADENCE of re-proof does not exist. | S | Count is as of 2026-08-09; not recounted. |
| 2026-08 | DoD row 13 text (#1231, #1324, #1389) | `oracle_mutation` score ROSE as the audit ran LESS because partial results dropped out of the denominator; a failure classifier asserted budget exhaustion without reading the budget. | S | Found by reading code, not by any gate (the row says so). |
| 2026-09-23 | `docs/research/corpus-extraction-contract-2026-09-23.md` | Reference-corpus extraction ran 2026-09-23 (3.00 h, 7,341,217 articles) against a contract revised after a review that found 19 defects, then 4 more. | S | See the note on which "corpus" this is, in (e). |
| 2026-09-24 | memory file `project_corpus_accuracy_state.md` (outside repo) | LA bars B1 to B9 on #1616; real-store baseline recorded on a branch; order #1616, then #1641, then #1648; no weekly run. | S (memory only) | On main I found `shared/corpus/reader.py` but no `evals/corpus_accuracy*` files; the suite is described as living on a feature branch. Current state not verified. |
| ongoing | `.claude/agents/dod-witness.md`; `tools/probes/dod_evidence_audit.py` | The witness agent's first action is the audit that says, per row, whether evidence was ever banked; a blind instrument and a missing run look identical and need opposite work. | S | I did not run the audit. |
| ongoing | `docs/quality/dispatch-quality-ledger.md`, `docs/FLEET_DISPATCH_LOG.md` | Durable per-run grading rows and fleet KPI log (merge rate, parked and stalled rates). | S (existence only) | Contents not read. |

### (d) Layers of zoom
1. **Why a coder at all.** UC-005 describes a local code-generation service so proprietary source never leaves the machine (`Use Cases_FINAL.md`, USE-CASE-005). The shipped form is the headless dispatch, not the original microservice sketch.
2. **What "working" means.** The DoD has capabilities 1 to 7 for one honest dispatch, 8 to 10 added 2026-08-06 for multi-page websites, and 11 to 21 ratified 2026-08-07. Rule of admission: a criterion that cannot be observed does not belong.
   1. **Status vocabulary** (DoD "Status legend"): LIVE (observable executed end to end, run cited), ARMED, PARTIAL, UNKNOWN, STOOD-DOWN, plus UNVOUCHED. Enforced by `tests/security/test_coder_dod_grammar.py`.
   2. **Two acceptance tests.** One dispatch an operator drives himself; a multi-run convergence test. The second is recorded as not executable on the battery path (#1381), which the LA answered by deciding "fresh on the battery, continue on demand" (ROADMAP row 8).
3. **How a job runs.** Plan, decompose and oracle-author on the resident 14B; swap to the 30B coder on OVMS (the OpenVINO Model Server); static pre-gate, import probe, smoke, wave gate, job oracle (all deterministic); advisory reviewer; report. One 30B load per dispatch with the critic dormant (`heterogeneous-multimodel-dispatch-recommendation-2026-07.md`, window A/B/C).
4. **Who grades the grader.** `shared/instrument_registry.py` (every reported number must be born "unmeasured"), `shared/fleet/oracle_qa.py`, `shared/fleet/oracle_mutation.py`, the guest-VM clean-room oracle. `CLAUDE.md` status_snapshot says the mutation, green-audit and lint instruments are still Python-only (stated there, not re-derived by me).
5. **The measurement problem in three examples.**
   1. Denominators: "once in eighteen" (ROADMAP), "eight runs" versus 11 versus 17 (DoD row 21), and a different pair in `CLAUDE.md` status_snapshot. Each is correct under its own grouping rule; none says which rule a new run should use.
   2. A true observation supporting a false claim: the ROADMAP's retracted measurement 2 (#1413, "the finish-line exam waits on a decoration") was right about the plan file and wrong about the code path.
   3. A gate that cannot fail: the phone-width check passed a page with no width limit because content without a limit never overflows a phone (ROADMAP "Right now").
6. **Smallest detail.** DoD row 6: `state/research-usage.jsonl` unchanged at 1,990 records on 2026-08-16, 1,986 of them plan-time grounding (stood down) and 4 developer probes: zero coder lookups ever.

### (e) Open questions and the observable that closes each
| Question | Observable |
|---|---|
| Have any DoD rows moved since their last dated line? | Run `python tools/probes/dod_evidence_audit.py` and compare with the status lines (not run by me). |
| Which denominator is the B9 success rate? | One stated grouping rule (goal hash and repository) written beside the number; recount from `scorecard.json` verdicts per DoD row 21 method. |
| Does the reference-corpus programme (#1616 / #1641 / #1648) belong to the coder at all? | DEC-13 in `docs/DECISION_REGISTER.md` describes #1616 as an offline Wikipedia-snapshot reference tier for the assistant, while DoD row 6 is the coder's API-documentation lookup. Whether they share a store is not verified; closes by reading the #1616 and #746 ticket descriptions. |
| Is the node/web path of the mutation and audit instruments built? | `shared/fleet/oracle_mutation.py` handles node inputs and a non-Python mutation test exists (#1385 is named as the largest remaining bar on the Python stand-down). |
| Does a built site pass his hands? | The LA fills the #1343 checklist; the escaped-defect counter (DoD row 12) can take no other input. |
| Does a refused exam get repaired for node? | A banked run where `job_acceptance` ran for a web card (#1410 was still "not-run" on 2026-08-16). |
| Is the heterogeneous recommendation still sound after the thinking-gate retraction? | Re-read its decision table against the 35B-A3B verdict after lesson 369's fix; not done. |

### (f) Decisions
Made: goal statements (LA 2026-07-30, 2026-08-06); carry-on rule and Python pause (2026-08-15); nightly battery cancelled (DEC-14); Qwen3-14B stays (model-upgrade watch in `CLAUDE.md` and memory); research-grounding validation design (session). Waiting for the LA: #1343 hands-on verdict; whether a job may pass with requirements never checked; what success rate is acceptable (ROADMAP "Still yours, later"); the items on the status_snapshot LA queue.

### (g) Tickets (from cited files; text not read)
#670 (dispatch) · #740 (fleet maturation) · #746 (research grounding) · #838 (candidate protocol, via ADR-038) · #1181, #1182 (overhaul gaps) · #1195 (defect inventory) · #1231, #1324, #1389, #1390 (grader honesty) · #1321, #1381 (carry-on) · #1343 (site verdict) · #1345, #1406 (hands found what gates passed) · #1385 (node mutation path) · #1410, #1413 (exam repair, rejected claim) · #1411 (the roadmap) · #1435 to #1439 (website checks) · #1616, #1641, #1648 (reference corpus, per memory) · #930 (35B brain).

### (h) Raw sources and where they are
In repo: `docs/design/` (DoD, completion map), `docs/ROADMAP.md`, `docs/research/coder-capability-2026-07/`, `docs/quality/`, `docs/evidence/fleet_task_timing_sweep_2026-07-29.md`, `docs/handoffs/` (landing cards, gitignored per `.claude/rules/handoff.md`), `docs/performance/` (for example `b5_coder_fleet_budget_2026-08-06_17-09-57.json`). Outside the repo: `C:/Users/mrbla/agentic-setup/state/fleet-runs/` (run records; existence confirmed, contents not read by me), `C:/Users/mrbla/agentic-setup/state/research-usage.jsonl` (cited by DoD row 6; not opened), the corpus worktrees `C:/Users/mrbla/blarai-wt-1616-accuracy` and `C:/Users/mrbla/blarai-wt-1648-retrieval` (existence only).

---

## Card F. Self-governance boundary, the Coordinator and supervised autonomy

### Summary (5 lines)
1. The LA ruled on 2026-07-11 that BlarAI has zero write path to its own governed core (code, config, prompts, policy, models, governing documents). Its self-directed output is advice for humans, never action. The rule lives in ADR-039 and in `CLAUDE.md` `<blarai_identity>`.
2. The Coordinator is the project-manager role BlarAI is growing into: a heartbeat wake cycle that watches work, keeps the ticket board honest and proposes next steps for the LA to approve. `default.toml` reads `[coordinator] enabled = true`, `heartbeat_enabled = true`, `shadow_mode = true`, `enabled_auto_classes = []`: awake and watching, speaking to nobody, allowed to act on nothing.
3. Autonomy is a ladder with a closed list of five action classes, all off. Moving a class up needs an LA ceremony, a register row and a per-class "Rule of Two" analysis. Graduation numbers were fixed in advance and ratified on 2026-07-23; graduation itself (#855) is held.
4. A reading finding for the LA to weigh: of the seven controls, the boot-time canary (control 6) and signed-policy verification (control 7) have no caller outside their own package, by my search. ADR-039 and the module docstring both call them dormant. Not yet confirmed by a live boot.
5. Not verified: whether tickets #813 to #868, #855, #1067, #1068 have moved; the contents of the shadow journal; whether the canary is called by some path my search could not see.

### (a) The question
How does a system that proposes work on its own backlog stay structurally unable to change itself, and what evidence has to exist before it may act without asking?

### (b) Current answer and status
**Decided as doctrine; partly built; autonomy deliberately at zero.**
- *Decided* (LA, 2026-07-11, #841 c.1798 and c.1812 per the plan): the two-domain model, governed core versus workspace. ADR-039 was promoted from draft and approved on 2026-07-12 ("I read adr-039 and I love it! approved! proceed!", quoted in the ADR header).
- *Live in shadow* (LA-present ceremony 2026-07-14, `docs/DECISION_REGISTER.md` update of that date): the heartbeat runs 15-minute cycles with all board-visible and operator-visible output diverted to a born-encrypted shadow journal. Two independent locks on live output: `heartbeat_enabled` and `shadow_mode`, the second flipped only at the #855 graduation ceremony.
- *Live read surface* (LA ceremony 2026-07-15): `/coord status` (register update of that date); grants no write authority.
- *Ratified* (LA, 2026-07-23, #1068): graduation criteria set before the measurement window, ceremonial demotion now, automatic demotion deferred (`docs/governance/coordinator_graduation_criteria_2026-07-23.md`). #855 graduation stays HELD (register update 2026-07-23, c.2438).
- *Dormant in config* (read today): `work_origination_enabled = false`, `swap_doom_checks_enabled = false`, `require_signed_policy = false`, `policy_path = ""`.
- *Open*: the Tier-2 relaunch mechanism for supervision (a recommendation awaiting the LA in `audit14`), and whether the telemetry layer is funded (`audit15`).
- Deciding documents: `docs/adrs/ADR-039-Coordinator-Self-Governance-Boundary.md`, `docs/research/coordinator-program-plan-2026-07.md`.

### (c) Evidence table
| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-07-11 | `docs/research/coordinator-program-plan-2026-07.md` | The design: two domains; seven structural controls; Kanban method on Vikunja; phases C0 to C5; a heartbeat and a work-origination loop are the two genuine gaps. | R | Status "design approved, design-only" at its date; independent review found 13 issues, all dispositioned. |
| 2026-07-11 | `docs/research/coordinator-self-governance-research-2026-07.md` | Self-modification is a named risk class; enforcement must sit in a higher privilege domain than the agent; the design maps onto OWASP LLM06, CaMeL, the Rule of Two. | V (cited external sources) | Its section 12 is a third-pass check against the live system. |
| 2026-07-11/12 | `docs/adrs/ADR-039-Coordinator-Self-Governance-Boundary.md` | Governed core enumerated; seven controls; autonomy ladder (section 2.10); second-pass hardening (2.14); claim discipline (2.17): until control 7 ships the claim is only "safe under expert operation". | R + decision | Amendments 1 and 2 add a documentation account and a hardlink defence. |
| 2026-07-11 | `docs/research/coordinator-operator-guide-2026-07.md` | Plain-language guide: `/coord status`, the digest, the briefing; "you currently check on the machine; after this, the machine checks in with you". | R | Header says nothing described there was built at its date. |
| 2026-07-14 | `docs/research/c3-heartbeat-design-2026-07.md` | Heartbeat design: age definition, launcher integration, dead-man check outside the heartbeat, two-lock output router, quiet-queue tripwire; adversarially reviewed (5 major findings applied). | R + S | A draft for LA checkpoint at its date; build later merged per the register. |
| 2026-07-17 | `docs/research/audit14-supervision-recommendation-2026-07.md` (#813) | Two tiers of supervision (in-process health supervisor, out-of-process relauncher); reject the Windows Service path (Session 0 has no GPU or desktop); one LA decision: the Tier-2 mechanism. | S (code-grounded) + R | Sub-tickets #865 to #868 named; their state not verified. |
| 2026-07-17 | `docs/research/audit15-telemetry-recommendation-2026-07.md` (#814) | A local, metadata-only, in-process telemetry layer with no network code; durable log under `%LOCALAPPDATA%`, not the public-synced `docs/performance/`. | R | Recommendation only; nothing built by its own header. |
| 2026-07-21 | `docs/research/graduated-autonomy-research-2026-07-21.md` | Groundwork for taking `enabled_auto_classes` from empty to first-class; ADR-039 leaves undesigned the threshold, the per-class analyses, the order, and any demotion. | S + V | External reads done by subagents with read-levels flagged per item. |
| 2026-07-22 | `docs/performance/coordinator-shadow-precision-2026-07-22.md` | Re-shadow window: 7 decisions across 7 runs all correct; the words guard caught 0 of 1 false statements and falsely refused 1 in 34 cycles. Not a graduation-earning record. | M (shadow journal) | Measurement only, per its header. |
| 2026-07-23 | `docs/governance/coordinator_graduation_criteria_2026-07-23.md` | Decisions layer: N at least 60 with zero errors (14 of 14 observed so far); words layer separate; demotion ceremonial now. | R + decision | Numbers are ratified pre-specification; risk tolerance is the LA's. |
| 2026-10-11 | `shared/coordinator/governed_core.py`, `shared/coordinator/config.py` (function `default_governed_core_roots`) | Severance is by identity (resolved path, inode, link count, worktree pointer), not by name; the root set includes the repo, the agentic-setup fleet root and the coordinator store. | S | Contrast with the older name-based refusal at `shared/fleet/dispatch.py` line 43 (`_FORBIDDEN_REPO_ROOTS`), still present. |
| 2026-10-11 | search of `shared/`, `services/`, `launcher/`, `tests/`, `tools/` | `run_boot_canary`, `assert_boot_boundary` and `verify_policy_integrity` are referenced only inside `shared/coordinator/` and its tests. | S (search) | A negative search; a call through a name my pattern missed is possible. |
| 2026-10-11 | `services/assistant_orchestrator/config/default.toml` lines 1128 to 1213 | Coordinator flags as listed in (b). | S | Read today. |
| 2026-07-12 | DEC rows for ADR-039 in `docs/DECISION_REGISTER.md` (line 61 and the 2026-07-14, 07-15, 07-23 updates) | The register carries each ceremony. | S | Register rows read in part. |
| ongoing | memory `project_blarai_self_governance_boundary.md` (outside repo) | The same decision with its reason: the LA intends to distribute BlarAI to non-technical operators, so safety cannot rest on vigilance. | S (memory) | Names the code anchor as `shared/fleet/dispatch.py:40`; the symbol is now at line 43. |

### (d) Layers of zoom
1. **Why a fence.** A coordinator that proposes work on BlarAI's own backlog sits one step from a fleet coding against BlarAI. The loop is cut by structure.
   1. **What is in the governed core** (plan, section "Self-governance boundary"): runtime code and tests, all config flags, prompts and policy, the preference tier and standing-instruction memory, model weights and keys, governing documents, the coordinator's own rulers, the heartbeat trigger, the fleet's graders and harness config, and the proposal store.
   2. **The one allowed channel:** the human-governed development path (LA and Claude sessions, branches, gates, ceremonies).
2. **The seven controls** (ADR-039 section 2.2): (1) identity-based target severance at every action chokepoint; (2) self-work advisory-only with structural provenance; (3) instruction-channel integrity; (4) config immutable from inside; (5) multi-operator defaults, ladder fully off on a fresh install; (6) boot canary and refuse-to-start; (7) signed policy verification.
   1. **Built and called:** control 1 is used by the heartbeat (`shared/coordinator/heartbeat_cycle.py` calls `derive_workspace_target`); control 5's predicate is `autonomy_all_off` in `shared/coordinator/config.py`.
   2. **Built, apparently not called at boot:** controls 6 and 7 (see (c)).
3. **The ladder.** Five closed classes: ticket-hygiene, stall-redispatch, readiness-refinement, reclassification, work-origination (`shared/coordinator/config.py`, per the graduated-autonomy research). Unknown names in config are dropped fail-closed.
4. **The two locks on speech.** `heartbeat_enabled` plus `shadow_mode`; shadow resolution is inverted fail-closed toward true. Machinery-health alarms are never shadow-gated.
5. **Graduation is two layers.** Decisions (deterministic, a statistical floor) and words (model-written digest sentences, guarded by a lexicon with a known weakness). They graduate separately.
6. **Smallest details.** Draft cap on coordinator model drafting set from 1024 to 128 new tokens at the 2026-07-14 ceremony, bounding a chat turn's wait behind a draft at about 10 s instead of about 80 s (register row). Heartbeat interval 900 s, four times slower on battery, quiet window "23:00-07:00" (config lines 1159 to 1166).

### (e) Open questions and the observable that closes each
| Question | Observable |
|---|---|
| Does the backend refuse to start if the canary fails? | Boot the backend with a projects folder placed inside the governed core and observe a refusal; or find the call site. Today only tests call the canary. |
| Is `require_signed_policy` ever turned on? | `require_signed_policy = true` plus a TPM-signed policy file; today `policy_path = ""`. |
| What does the words guard need to earn graduation? | A window whose false-suppression figure meets Amendment 1 of the graduation criteria (varied phrasing) and a catch rate over more than one false statement (rebuild tracked as #1067). |
| Who or what demotes a graduated class? | A written design; ADR-039 designs flips up only; the LA deferred auto-demotion. |
| Which Tier-2 relaunch mechanism? | The LA's choice among the relauncher, a scheduled-task restart or a service; the audit recommends the first. |
| Do #865 to #868 and #878 exist as built code? | Search `launcher/` for the health supervisor; I did not find one by listing `launcher/` (not conclusive: a supervisor could live in `__main__.py`, which I did not read). |
| Does the Governator's observation of the door change this boundary? | `docs/research/GOVERNATOR_BRIDGE.md` decisions D1 to D6, all the LA's. |

### (f) Decisions
Made: the self-governance rule (2026-07-11); ADR-039 approved (2026-07-12); heartbeat shadow go-live and the 128-token cap (2026-07-14); `/coord` read surface (2026-07-15); graduation criteria and ceremonial demotion (2026-07-23); #855 graduation held. Session calls: dormant-until-ceremony posture for work origination and doom checks. Waiting for the LA: the Tier-2 relaunch mechanism and the observe-versus-act go-live split (audit14); funding telemetry (audit15, including whether fleet, appliance or both is its scope); the eventual graduation ceremony.

### (g) Tickets (from cited files; text not read)
#841 (epic) · #842 (C0, ADR-039) · #843 (C1) · #844 (C2) · #845 (C3 heartbeat) · #846 (C4) · #847 (C5 ladder) · #848 (self-governance controls) · #855 (graduation) · #1067 (prose guard rebuild) · #1068 (criteria) · #749 (Vikunja bridge) · #813, #865 to #868 (supervision) · #814, #878 (telemetry, dashboard) · #877 (daytime ceremonies session).

### (h) Raw sources and where they are
In repo: the files in (c); `shared/coordinator/` (15 Python files); `shared/tests/test_coordinator_boot_canary.py`, `shared/tests/test_coordinator_policy.py`; `docs/governance/coordinator_shadow_precision_report_2026-07-18.html`; `docs/governance/decisions_digest_2026-07-18.html` (existence only). Runtime data: the born-encrypted shadow journal under the coordinator store (location not checked; contents are encrypted by design).

---

## Card G. People-facing surface: UI, voice, images and the novice-operator design

### Summary (5 lines)
1. The daily face of BlarAI is the WinUI 3 desktop app (a native Windows 11 interface), talking to the Python backend over a named pipe (ADR-014, 2026-06-02). The earlier text interface (Textual TUI, ADR-009) is kept as a dormant fallback by the LA's explicit call.
2. Voice (Whisper-small speech-to-text on the Arc GPU, Kokoro text-to-speech on the processor) and local image generation (UC-010, `/imagine`, `/illustrate`, `/cartoon`, `/edit`) are live: the image flag reads `enabled = true` with a recorded go-live of 2026-06-16.
3. The design stance is that the LA is permanently non-technical: he directs by judgment, through gates, tickets and a growing set of double-click tools on his Desktop. The coder's "advanced intake" interview follows the same stance (plain-language questions, "I don't know" always acceptable).
4. The two non-developer guides, `docs/RUNBOOK_NON_DEV_OPERATIONS.md` and `docs/HOWTO_FEATURES_NON_DEV.md`, do not mention voice, images or WinUI by name (search, case-insensitive), so they trail the product.
5. Not verified by me: that the app builds and launches today, that the Desktop shortcuts work, ADR-033's body beyond its header, and the learning decks' contents beyond their READMEs.

### (a) The question
What does a non-technical operator see and touch, how did each surface get there, and where does the guidance for him lag the product?

### (b) Current answer and status
**Decided and live, with stale guidance.**
- *Decided* (LA, 2026-06-02, ADR-014): native WinUI 3 over a named-pipe JSON-RPC bridge, no listening network socket. The ADR-009 TUI is superseded as the primary surface but "retained in-tree as a dormant fallback, not deleted".
- *Decided* (ADR-019, 2026-06-03): the WinUI app runs de-elevated at medium integrity while the launcher needs administrator rights for Hyper-V.
- *Decided* (ADR-017, 2026-06-02): voice is fully local, fail-soft (text chat continues if a model cannot load).
- *Live* (read today): `[image_generation]` `enabled = true` (default.toml line 327, "GO-LIVE 2026-06-16 (#666)").
- *Live* (read today, a different thing): `advanced_intake_interview_voice = true` ("GO-LIVE 2026-07-29 (#1165 M1, LA-present ceremony)") is the interview's wording style, not audio.
- *Stale text noticed*: `docs/adrs/ADR-033-Local-Generative-Imaging.md` header still reads "PROPOSED ... Built DORMANT" while the config shows go-live; the register row for ADR-033 (line 53) carries the decision.
- Deciding documents: ADR-009, ADR-014, ADR-017, ADR-019, ADR-033; `docs/design/advanced_intake_novice_interview_maturation_DESIGN.md`.

### (c) Evidence table
| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| 2026-02-23 | `docs/adrs/ADR-009-Assistant-Interaction-Surface.md` | The terminal interface (Textual); a local web UI was rejected for needing a listening socket. Superseded 2026-06-02. | R | Header states supersession. |
| 2026-06-02 | `docs/adrs/ADR-014-WinUI3-Native-Surface-NamedPipe-Bridge.md` | WinUI 3 front end holds no business logic; named pipe (a kernel object, remote clients rejected) carries length-prefixed JSON. | R | The pipe-versus-HTTP reasoning mirrors ADR-009. |
| 2026-06-02 | `docs/adrs/ADR-017-Local-Voice-STT-Whisper-TTS-Kokoro.md` | Probe on the Arc 140V: Whisper-small transcribed a 2.7 s utterance in 0.53 s (load 5.87 s once); Kokoro at real-time factor 0.30 on CPU; audio crosses the same pipe as base64. | M (probe, #539) | Numbers are the ADR's, "measured, not assumed"; not re-run. |
| 2026-06-03 | `docs/adrs/ADR-019-De-Elevate-WinUI-Surface-Medium-Integrity.md` | A filtered-token launch keeps the UI at medium integrity. | R | Body not read beyond the context. |
| 2026-06-16 | `docs/adrs/ADR-033-Local-Generative-Imaging.md`; `docs/runbooks/uc010_image_gen_go_live.md`; `docs/runbooks/uc010_image_gen_operator_guide.md` | Uncensored SDXL INT8 finetune on the Arc GPU; content safety is governance plus a one-time attestation, not a classifier; images are born-encrypted and leave only through `/save`. | R + S | The go-live runbook's own banner says the ceremony has been performed. |
| 2026-10-11 | `services/assistant_orchestrator/config/default.toml` line 327 | Image generation flag is true. | S | Read today. |
| 2026-07-21 | `docs/research/ui-seam-and-task-grain-research-2026-07-21.md` | Check the page structure the user sees; one-file tools should be one build task. | V | See Card E. |
| 2026-07-29 | `docs/research/novice-interview-template-research-2026-07-29.md` | A seven-rule reusable interview: life not software, one decision per question, three ways to answer, concrete beats abstract, the interviewer proposes and the person vetoes, "I don't know" never blocks, nothing is final until the playback. | R + V | Status "research, no build implied"; part 4 separates sources read from sources only seen. |
| 2026-07-29 | `docs/design/advanced_intake_novice_interview_maturation_DESIGN.md`; default.toml line 880 | The interview voice (Part 1 wordings, mistake rules) went live in an LA-present ceremony. | S | Maturation items M2, M3, M6 are named unbuilt in the status_snapshot and `docs/ROADMAP.md`. |
| 2026-08-08 | DoD row 2 (`docs/design/CODER_DEFINITION_OF_DONE.md`) | The LA's first run of the interview: plain-language questions, "I don't know" accepted, his words played back, no technical question asked; the build then merged 3 of 8 tasks. | M (supervised) | Run `20260808-104536-bd`. The exercise also found four defects, three in its own printed instructions. |
| ongoing | `docs/RUNBOOK_NON_DEV_OPERATIONS.md`, `docs/HOWTO_FEATURES_NON_DEV.md` | Cold start via `launch_blarai.bat`; sessions, Ctrl+N; escalation path. A case-insensitive search for "voice", "image", "winui", "tui" found none in either file. | S | They carry no date line; the guide to image commands lives elsewhere. |
| ongoing | `docs/runbooks/what_blarai_is_allowed_to_do.md` | One command (`python -m shared.governance.permission_profile`) prints what BlarAI may do, reading live config and code, so it cannot go stale. | S | Run on 2026-10-11 by the batch 2 author (Card A). |
| ongoing | `docs/runbooks/LA_OPERATIONS_INDEX.md` | The operations index; banner says the autonomous agent fleet it describes was retired (verified 2026-07-20, #979 R3). | S | Dead links struck through with replacements. |
| 2026-10-11 | the LA's Desktop folder | Eight items: `BlarAI status.cmd`, `PAUSE BlarAI.cmd`, `RESUME BlarAI.cmd`, `Check last backup.cmd` and `.ps1`, `Review the website BlarAI built.lnk`, `TRY the new BlarAI brain (35B).lnk`, two prompt text files. `BlarAI status.cmd` calls `blarai-ops/control/blarai-pause.ps1 -Status`. | M (listing) | I did not run any of them. |
| ongoing | `docs/learning/lessons_deck/README.md`; `docs/learning/fable5_deck/` | A study deck over the lessons for the LA's AIGP (IAPP AI Governance Professional) certification, with a 31-lesson core path. | S | README counts "107 numbered lessons plus 19" at its date; LESSONS.md now indexes up to 385, so the deck trails (currency not verified). |
| 2026-06 | `docs/security/capstone_explainers/host_guest_secure_dataflow.md`; `docs/security/explainers/host_guest.html` | Plain-language explainers of the host-to-guest flow. | R | Existence only (see Card batch 1). |

### (d) Layers of zoom
1. **Who the interface is for.** A permanently non-technical operator who owns the why, not the how (`CLAUDE.md` `<user_operator>`). Designs are judged by whether he can answer them yes or no.
2. **Surfaces.**
   1. **WinUI 3 app** (`services/ui_winui/`, C# front end; the C# build must use `-p:Platform=x64`). Back end: `services/ui_backend/` behind the named pipe; gateway: `services/ui_gateway/`.
   2. **Textual TUI** (`services/ui_shell/`): dormant fallback, under test, no new capabilities.
   3. **Voice** (`services/voice/`): microphone in the input, a voice-output setting and a per-message play button, all over the same pipe.
   4. **Images:** commands in a table in the operator guide; the model is gitignored, so a checkout without weights loads nothing regardless of the flag (config comment).
3. **How the operator runs things.** Double-click launchers on the Desktop; the dispatch exercise printed in chat and executed first (DoD row 2: "an exercise's commands must be executed before they are printed"); ceremonies offered batched per tier.
4. **How the interview treats a novice.** Phase 0 sets the table in four sentences; every question has an own-words, a pick-one and a "you decide" path; the playback is the contract (template Part 1).
5. **Where the hands outrank the gates.** Twice a delivered result passed every automated gate and failed his hands (#1345, #1406 per `CLAUDE.md`); DoD row 9 and the ROADMAP rank 7 (#1343) keep that input.
6. **Smallest details.** The instructions the app prints must parse in the app: `test_operator_instructions_parse.py` convicted six more shipped instructions on its first run (ROADMAP "How today's work connected", point 2).

### (e) Open questions and the observable that closes each
| Question | Observable |
|---|---|
| Do the non-developer guides need voice, image and WinUI sections? | An LA read of both files against the running app; or a generated list from `capabilities(...)` comments in default.toml. |
| Does the app build and launch from a clean checkout today? | `dotnet build` with `-p:Platform=x64` and a launch; not run by me. |
| What does voice cost in memory beside the 14B? | `docs/performance/README_coresident_ut.md` and the co-resident benchmark JSONs hold co-resident measurements; whether voice is covered was not read. |
| Is the interview's M2 (photos and words the site should contain) wanted next? | The LA's read of the interview template (named "still yours" in the ROADMAP); #1165 residual. |
| Is the lessons deck current? | Rerun `docs/learning/lessons_deck/build_lessons_deck.py` and compare unit count with LESSONS.md. |
| Does a speech request ever leave the machine? | A packet capture during a voice turn; the design says no network code; the egress-guard lock tests cover imports, not the voice path specifically (not checked). |

### (f) Decisions
Made: WinUI as primary, TUI retained dormant (ADR-014 / ADR-009, 2026-06); de-elevation (ADR-019); local voice (ADR-017); image generation go-live (2026-06-16, LA-present, with content attestation). Waiting for the LA: his read of the interview template (ROADMAP); what to do about voice, narration and animation for generated sites (ROADMAP: "needs a scope decision from you first").

### (g) Tickets (from cited files; text not read)
#539 (voice probe) · #541 (optimum exporter break) · #666 (UC-010) · #703 (illustrations, per memory) · #1031 family (advanced intake) · #1165 (interview maturation) · #1335 (exercise instructions) · #1343, #1345, #1406 (hands found defects) · #1412 (live verification) · #979 (autonomous fleet retirement).

### (h) Raw sources and where they are
In repo: `services/ui_winui/`, `services/voice/`, `services/ui_shell/`, `docs/adrs/`, `docs/runbooks/` (32 entries at this listing, including the go-live ceremonies), `docs/learning/`, `branding/`, `demo.html`, `docs/demo/PORTFOLIO_DEMO_PLAN.md`. Outside the repo: the Desktop folder (listed today), `C:/Users/mrbla/blarai-ops/control/` (referenced by the status script; contents not read).

---

## Card H. Measurement discipline and the evidence system

### Summary (5 lines)
1. BlarAI treats a measurement as a claim that must survive its own instrument. The machinery: the standing gate (`docs/TEST_GOVERNANCE.md`), disposition records checked by `scripts/verify_disposition.py`, the lessons file with a numbered, permanent index, performance entries with named conditions, and visible in-place retractions.
2. The project has retracted its own numbers many times and recorded how. Three are central: the thinking-gate verdict on the 35B model (lesson 369), and the 14B prompt-injection "failures" that came from the test harness (lessons 371 and 372).
3. The standing gate's current count lives in one line, `LIVE_GATE_BASELINE` in `docs/TEST_GOVERNANCE.md`; its conditions (elevation, app up or down, worktree versus real checkout) change the skip column, so a figure without them is not a figure.
4. Variance first: unchanged configuration measured 16.55, 11.82 and 9.59 tokens per second in one hour (#1487), and sustained decode on this laptop slows about 3 times within about 2 minutes. Speed comparisons gate on a thermal zone at or below 72 C and use visit means.
5. A gap found by this card: the performance policy (`docs/performance/POLICY.md`, 582 lines, with its own gate) exists only on branch `docs/1485-performance-tracking-policy` in a side worktree, not on main; a memory file cites it as if present. Not verified: whether that branch has been merged by the time you read this.

### (a) The question
How does BlarAI decide that a number, a test result or a review finding is true enough to act on, and what happens when it is later found wrong?

### (b) Current answer and status
**Decided and enforced in many places; with an unmerged piece.**
- *Decided/enforced*: the standing gate's bar is 0 failed, 0 skipped in a clean environment; a skip is investigated (`docs/TEST_GOVERNANCE.md` section 1). Gate-enforced freshness: `tests/security/test_doctrine_freshness.py`.
- *Decided/enforced*: every review, audit or verification pass gets a disposition record with a machine-checkable block; deferral needs a predicate someone can observe (`scripts/verify_disposition.py`, `tests/security/test_disposition_discipline.py`, rule in `CLAUDE.md` `<deferral_discipline>`).
- *Decided/enforced*: lessons are permanent numbers, searched before minting; a third recurrence must ship a structural control (`LESSONS.md` "Rules of this file").
- *Decided*: the measurement protocol for model evaluation (ADR-047, 2026-10-05): cold thermal gate, visit means, limits pre-registered on the ticket, disclosed exclusions, retractions in place, data published.
- *Decided* (LA standing rules in the global instructions): no conclusion from one observation per arm; control before reporting; one report at the end.
- *Not on main*: the performance tracking policy and its gate test (see Summary 5).
- Deciding documents: `docs/TEST_GOVERNANCE.md`, `docs/adrs/ADR-047-Model-Evaluation-Protocol-Cold-Gate-Pre-Registration-and-Visible-Retractions.md`, `LESSONS.md`.

### (c) Evidence table
| Date | Document path | What it found, one plain line | Grade | Confidence note |
|---|---|---|---|---|
| ongoing | `docs/TEST_GOVERNANCE.md` section 1, rules 1 to 10 | How to run a gate so the figure means something: nothing else heavy running, predict the figure and the skip column first, capture full output, never edit mid-gate, a worktree figure is not the baseline, state elevation, time only from the idle-gated instrument, parallel figures name their group count. | S | The current baseline is the `LIVE_GATE_BASELINE` line (line 73); not copied here because it rots. |
| 2026-10-07 | `docs/performance/gate_runtime_2026-10-07/` (cited by TEST_GOVERNANCE rule 8) | Real gate wall-clock comes only from the idle-controlled runner; run-to-run spread 1.4 % (09-22 tree) to 3.5 % (current). | M | Spread is the instrument's own, stated in rule 8. |
| 2026-09-01 | `docs/performance/POLICY.md` on branch `docs/1485-performance-tracking-policy`, read in worktree `C:/Users/mrbla/blarai-wt-perf-policy` | Four incidents, including a configuration that fell from 38.58 tokens per second (2026-06-29) for an unestablished cause and an unmeasured prefill flag that ran two months; same config read 16.55, 11.82, 9.59 tokens per second inside one hour. | S (branch file) | Not on main (`docs/performance/` on main has no POLICY.md; its gate test is absent from `tests/security/`). |
| 2026-10-05 | `docs/adrs/ADR-047-...md` | Cold protocol primary; thermal zone at or below 72 C before each generation; unit of analysis is the visit mean; pre-registered limits (under about 5 % decode difference is not a finding; ratio refused if an arm's variation exceeds 15 %); exclusions disclosed as post hoc; retractions visible. | S + decision | Born of the Qwen3.5 arcs (#1663, #1665); decides nothing about replacing Qwen3-14B. |
| 2026-10-04 | memory `reference_arc140v_thermal_throttle_cold_gate.md`; `PERFORMANCE_LOG.md` entry of 2026-10-04 | Decode went from 48 ms to about 160 ms per token over about 2 minutes (thermal zone 77 to 96 C); rest of 20 to 60 s recovered it in 4 of 5 probes. | M | Entry cited by the memory file; not re-opened by me. |
| 2026-09-22 | `docs/archive/lessons/LESSONS_ARCHIVE.md`, lesson 369; `PERFORMANCE_LOG.md` entry of 2026-09-22 (evening) | A 22/40 score that stood two months as proof the 35B could not suppress its reasoning came from the harness: the chat template emitted a bare opening think tag whenever the thinking flag was unset. Retracted; the verdict had gated a brain swap. | M + S | Lesson text is the authority; the practice: read the setup's rendered prompt before believing a verdict. |
| 2026-09-22 | same archive, lessons 371 and 372; `PERFORMANCE_LOG.md` lines 800 to 816 (the four instrument defects) | The agentic and conversation suites scored 0 of 0 cases in the gate and exited green; the tool loop took the plain branch for retrieval results, so the injection cases ran without datamarking, producing three "security failures in the shipped 14B" that were artefacts. | M + S | Disposition `docs/reviews/agentic-eval-suite-disposition-2026-09-22.md`. The 14B numbers are retracted and attributed. |
| 2026-07-30 | `shared/instrument_registry.py`; DoD rows 7, 13, 14 | An instrument is born unmeasured; nine instruments were found in one day reporting a pass or a number they had not measured, all by reading code, none by a gate. | S | See Card E. |
| 2026-10-04/05 | ADR-047 Decision 6 | In-place retractions in the Qwen3.5 arc: "byte-identical in every check / 63 of 63" (actually 2 of 366 and 1 of 377 calls differ mid-reply); a hypothesised cause for a 4B failure; a recommended deny rule; a CPU-overlap explanation. | S | Wrong version stays visible. |
| 2026-08-15 | `docs/ROADMAP.md` measurement 2 and item 2 | A true observation (the exam lists six siblings as prerequisites) supported a false conclusion; rejected after reading the code path; the overstated version is left visible. | S | The roadmap names "six times reading was wrong; running was wrong none". |
| 2026-10-04 | `docs/research/jev-policy-agent-ideation-2026-10-04.md` | 9B model evidence corrected: 6 informative rows not 10; corrections visible in the file. | S | See batch 1 and 2. |
| ongoing | `scripts/verify_disposition.py`; `docs/reviews/` (147 top-level files, 116 with "disposition" in the name at today's listing) | The verifier fails on a finding with no row, a FIXED row with no commit-ish evidence, a DEFERRED row with no ticket or a filler predicate ("follow-up", "next session"). | S + M (listing count) | Counts are filename counts, not a count of findings. |
| ongoing | `LESSONS.md` (lessons indexed through 385) | Hot index of every lesson, a canonical tier, a 32-entry residency tier; full text in the archive; budget 120 KB. | S | Recurrence tallies live in the archive and the index flag, not in the 32 hot copies, by design. |
| ongoing | `FIELD_NOTES.md` (1,478 lines) | Mechanical gotchas by surface; grep before touching a named surface. | S | Not read beyond its length and the journal rule. |
| ongoing | `.claude/rules/performance.md`; `PERFORMANCE_LOG.md`; `docs/performance/` | Every hardware or model performance test is recorded when it runs, with hardware, OpenVINO and driver versions, methodology, numbers and what was not measured. | S | Upload to the public Hugging Face dataset is a stated part of every measurement arc (memory). |
| 2026-10-10 | `docs/performance/containment_probe_2026-10-10/`, `PERFORMANCE_LOG.md` entries 2026-10-10/11 | The containment study copies its timings and logs into the performance record. | S | See Card in batch 1. |

### (d) Layers of zoom
1. **Why discipline.** The project's own record: several conclusions drawn and retracted in single afternoons; instruments that err only toward looking fine.
2. **The layers, from the bottom.**
   1. **Does it run?** The standing gate: selection and fast form in TEST_GOVERNANCE section 1; markers for hardware, winui and slow tiers run at their own ceremonies. LOCALAPPDATA is always redirected for pytest.
   2. **Can it fail?** Every control ships with a test that it blocks and a toggle test that the probe fails when the lock is off (`CLAUDE.md` security principle 12; DoD row 14; the instrument registry's toggle, seam and quiet tests).
   3. **Did the instrument look?** Reach before verdict: lesson 371 says read how many cases scored; the registry's "unmeasured" default is the same rule aimed at graders.
   4. **Is the setup the cause?** Lesson 369: read what you sent the subject. Lesson 372: driving a production function is not driving the production path.
   5. **Is the subject stable?** Lesson 370: before A versus B, run each against itself; the incumbent's stability is the control.
   6. **Is the machine the cause?** The thermal cold gate; ABA interleaving; unique nonce at the head of prefill measurements; ambient CPU recorded (memory `feedback_no_conclusion_below_measured_noise.md`).
   7. **Was the finding disposed?** Disposition records, one row per finding, FIXED / DEFERRED / REJECTED.
   8. **Was it banked where it was said?** Retractions go in the place the claim was made, the wrong version visible; lessons, journal, performance log, ticket comments.
3. **The retraction pattern.** Across the project: lessons 369, 371, 372 (above); ADR-047's list; the ROADMAP's measurement 2; the DoD's own corrections (for example "the schema holds no clarification key" became false, 113 of 223 records carry one); batch 1's corrected-claims table. The shape recurs: a number from one session is narrowed by an independent reader.
4. **Smallest details.** A gate that read 11658 passed / 3 skipped against a predicted 11661 / 0 hid an environment skip (TEST_GOVERNANCE rule 2). A parallel gate surfaced test-order dependence the serial run had hidden (#1707, rule 10). A timing figure taken while the operator works is contaminated: control tree 703 s versus 1632 s separated only because both ran idle (memory `project_gate_timing_instrument.md`).

### (e) Open questions and the observable that closes each
| Question | Observable |
|---|---|
| Is the performance policy merged and its gate live? | `docs/performance/POLICY.md` and `tests/security/test_performance_tracking_policy.py` exist on main. Today neither does. |
| Does every banked performance entry carry thermal state and run order? | A scan of `PERFORMANCE_LOG.md` entries for the stamp fields the policy requires; not run. |
| Do disposition counts reflect findings or filenames? | Parse the ```disposition blocks across `docs/reviews/` and count rows by status. |
| Are there unrecorded measurement results? | Compare `docs/performance/` JSON names to `PERFORMANCE_LOG.md` entries (batch 1 found the #1671 and #1689 spikes unlogged on 2026-10-11; a later commit added entries). |
| Has the quarterly lesson consolidation due 2026-10-01 happened? | Look for a consolidation entry in `BUILD_JOURNAL.md` or the lessons header; the snapshot says "Consolidation 2026-10-01"; contents not read. |
| Which reviews have no disposition record? | The batch 1 gap list names studies without one (landscape surveys, the July encryption evaluation, the feasibility study). |

### (f) Decisions
Made: gate bar and rules; disposition discipline; lesson curation; ADR-047 protocol (LA's requirements: upload to Hugging Face, three-repeat telemetry, pre-registration); LA standing rules on measuring and concluding (global instructions, 2026-09-01). Waiting for the LA: moving any test out of the standing gate (rule 9: his decision only); success-rate bars for the coder (Card E); the merge of the performance policy is a session matter, not an LA decision (not verified who holds it).

### (g) Tickets (from cited files; text not read)
#945 (doctrine freshness, lessons tiering) · #1485 (performance tracking policy) · #1487 (drift measurement) · #1594, #1597 (gate skip and loaded-gate incidents) · #1611, #1618, #1622, #1624, #1627, #930 (35B and eval instruments) · #1663, #1664, #1665 (Qwen3.5 arcs) · #1699, #1707 (gate timing and parallel) · #998 (evaluation assessment) · #1223 (nine instruments) · #1231 (reconciliation).

### (h) Raw sources and where they are
In repo: `docs/TEST_GOVERNANCE.md`, `docs/archive/test-governance-baseline-history.md`, `docs/reviews/`, `LESSONS.md`, `docs/archive/lessons/LESSONS_ARCHIVE.md`, `FIELD_NOTES.md`, `PERFORMANCE_LOG.md`, `docs/performance/` (741 files per `docs/INDEX.md`; counted by its author, not me), `docs/governance/agent-doctrine-evidence.md`, `scripts/verify_disposition.py`, `scripts/run_standing_gate.py`, `scripts/verify_roadmap.py`. Outside the repo or on a branch: `docs/performance/POLICY.md` and `BASELINES.md` in `C:/Users/mrbla/blarai-wt-perf-policy` (branch `docs/1485-performance-tracking-policy`); the Hugging Face dataset `blairducrayoppat/openvino-arc140v-lunarlake` (named in `.claude/agents/hf-dataset-publisher.md`; not opened).

---

## Connections (all [PROPOSED]; each pairs two real documents; none is tested)

1. **[PROPOSED] Heterogeneous-dispatch recommendation + the lesson 369 retraction.** `docs/research/heterogeneous-multimodel-dispatch-recommendation-2026-07.md` recommends consolidating onto the 35B-A3B for speed and one fewer model; `docs/archive/lessons/LESSONS_ARCHIVE.md` lesson 369 shows the thinking-gate verdict that blocked that swap was a harness artefact. Idea: re-read the recommendation's decision table with the verdict removed, and list which of its reasons (swap count, the #4139 gate, quality parity) still stand. Hypothesis: the recommendation's conclusion may be stronger than it looked, or may rest on other facts; nobody has recompared. Caution: Qwen3-14B stays per the model-upgrade watch; this is a re-read, not a proposal to swap.
2. **[PROPOSED] Graders are governed core + "graders graded".** `docs/adrs/ADR-039-Coordinator-Self-Governance-Boundary.md` puts the fleet's judge (verify gate, oracle machinery, harness config) inside the governed core ("the judge must not be improvable by the judged"), and `shared/coordinator/config.py` (`default_governed_core_roots`) already includes the agentic-setup root. `docs/design/CODER_DEFINITION_OF_DONE.md` row 13 asks that each grader be graded. Idea: use `shared/instrument_registry.py` as the authoritative list of what "the judge" is, and add a check that every registered instrument's file sits under a governed-core root. Hypothesis: today the two lists were written separately and nobody compared them.
3. **[PROPOSED] Controls 6 and 7 not called + the "built but wired into nothing" lesson class.** `shared/coordinator/boot_canary.py` documents itself as dormant until C1 wires it; `docs/TEST_GOVERNANCE.md` (section on seams, via `.claude/rules/testing.md`) names "control exists, nothing calls it" as a recurring failure. Idea: a reachability test that fails if a function named in ADR-039's control list has no non-test caller once the flag it guards is true. Hypothesis: the finding in Card F may be a real gap or a call my search missed; one live boot settles it.
4. **[PROPOSED] Graduated-autonomy "induced-proposal susceptibility" + the repaired agentic eval suite.** `docs/research/graduated-autonomy-research-2026-07-21.md` (ADR-039 section 2.16 requirement that the shadow suite be graded for induced proposals) and `docs/reviews/agentic-eval-suite-disposition-2026-09-22.md` (a tool-result injection harness whose datamarking path was fixed under lesson 372). Idea: build the coordinator's adversarial ticket-content cases on the repaired harness path, because the plain-branch defect would have invalidated them the same way. `evals/golden/coordinator.jsonl` exists; its contents were not read.
5. **[PROPOSED] Telemetry layer + the thermal cold gate.** `docs/research/audit15-telemetry-recommendation-2026-07.md` proposes rolling p50/p95/p99 latency and tokens per second; `docs/adrs/ADR-047-Model-Evaluation-Protocol-Cold-Gate-Pre-Registration-and-Visible-Retractions.md` shows heat alone can triple per-token time. Idea: include the thermal zone reading in each telemetry sample, so a production slowdown is never read as a regression without its temperature. Hypothesis: the audit does not mention temperature (not searched for in full).
6. **[PROPOSED] Novice-interview "assumptions flagged" + requirement-coverage reporting.** `docs/research/novice-interview-template-research-2026-07-29.md` (rule 6: "I don't know" becomes a stated default plus a flag) and DoD row 17 in `docs/design/CODER_DEFINITION_OF_DONE.md` (the exam covers what was asked; `tools/probes/requirement_coverage_report.py`). Idea: the report could print assumed-by-default requirements separately from requirements the LA actually stated, since the first set cannot be "covered" in the same sense. Hypothesis: the flag is recorded in the clarification record; its shape was not read.
7. **[PROPOSED] Self-updating capability list + the stale non-developer guides.** `docs/runbooks/what_blarai_is_allowed_to_do.md` (the command reads live config and cannot go stale) and `docs/HOWTO_FEATURES_NON_DEV.md` (no mention of voice, images or the app). `default.toml` carries `capabilities(...)` comment markers on each flag. Idea: generate the feature list of the how-to from the same markers, with a gate that fails when a live flag has no entry. Hypothesis: the markers are consistent enough to key on; not checked.
8. **[PROPOSED] User-visible-seam principle + the LA's hands.** `docs/research/ui-seam-and-task-grain-research-2026-07-21.md` (test the page structure the user sees) and `docs/ROADMAP.md` "Right now" (seven defects his hands found, zero flagged blocking; the stylesheet container never applied). The same principle applies to BlarAI's own app, not only the coder's sites: a headless render of the WinUI window text after a scripted turn. Hypothesis: the `winui` test tier already does part of this; its coverage of rendered text was not checked.
9. **[PROPOSED] Disposition verifier's predicate grammar + coordinator briefings.** `scripts/verify_disposition.py` refuses a deferral whose `blocked-by:` names nothing observable; `docs/research/coordinator-operator-guide-2026-07.md` has the Coordinator propose and the LA approve or deny. Idea: a coordinator proposal that parks or defers work carries the same observable predicate, validated by the same function, so a briefing cannot contain "later". Hypothesis: the proposal schema has no such field today (not read).
10. **[PROPOSED] Python stand-down + Python-only instruments.** `docs/ROADMAP.md` (the LA's stand-down: hold Python-side probing until the website side is on par, ends only by his act) and DoD row 13 / the status_snapshot (the mutation, audit and lint instruments are Python-only; #1385 names the node path as the largest remaining bar). The two statements form a dependency: the stand-down cannot end on evidence while the instruments that would show "on par" cannot see web. Idea: state that dependency on #1385 in the ROADMAP row so the LA's lift decision has a visible precondition.
11. **[PROPOSED] Retraction tables across the knowledge map + an enforced marker column.** `docs/research/KNOWLEDGE_MAP.md` section 5 (corrected claims, hand-written) and `LESSONS.md` lesson 385 ("a column that says enforced is a claim by whoever wrote the marker"). Idea: keep each map's corrected-claims list as a small structured file with the artifact path of the correction, and verify the pointers exist. This card's own list is the first candidate.

---

## Corrected claims (for these topics)

| What was claimed | What replaced it | Where (and status) |
|---|---|---|
| The finish-line exam waits on a decorative job, so one cosmetic failure discards the night's grade (ROADMAP measurement 2, item 2) | The grade never reads that task's status; the exam failed because it was refused (item 1) | `docs/ROADMAP.md`; ticket #1413 closed. Both versions visible. |
| "A refused exam is authority to strike tasks" (a 13:20 correction of the 08-15 survey) | A refused exam is never installed; the live hole was a partially accepted exam passing a guard that never read the verdict | `docs/ROADMAP.md` (superseded block); fixed `04d07953` per the file. |
| "The schema holds no clarification key of any spelling" (DoD row 2) | 113 of 223 records carry `spec.clarifications` | DoD row 2 re-sweep of 2026-08-14. |
| "Eight runs of B9" with no grouping rule | 11 completed runs under an explicit rule; 17 under another reading | DoD row 21, 2026-08-15. Status counts elsewhere (ROADMAP, status_snapshot) use further denominators. |
| The 35B "cannot suppress its reasoning" (22/40) | A harness artefact: the chat template opened a reasoning block | Lesson 369; `PERFORMANCE_LOG.md` 2026-09-22. Retracted. |
| "Three security failures in the shipped 14B" on tool-result injections | The harness took the plain result branch (no datamarking) and fed a prompt shape the 14B never receives; numbers retracted and attributed | Lessons 371 and 372; `PERFORMANCE_LOG.md` lines 800 to 816. |
| "MTP on and off outputs byte-identical in every check / 63 of 63" | Recomputed: 9B 2 of 366 calls differ, 4B 1 of 377, mid-reply | ADR-047 Decision 6. |
| "The slow visit overlapped review-agent CPU work (23 %)" | One 7 s sample; the 120 s mean was 16.8 %; the cause was rows that never reached the thermal gate | ADR-047 Decision 6; #1665 c.3856. |
| A loop that had "found, fixed and re-verified" a broken form (a claim in the DoD; the row is not identified in the ROADMAP text I read) | Retracted: the fix never landed; only his hands disproved it | `docs/ROADMAP.md` "Right now" (#1433 note). |
| "Python probes pause only overnight" | The pause covers daytime probes and ends by his explicit act | `docs/ROADMAP.md` "ANSWERED 2026-08-15" (#1385). |
| The measurement of the self-governance code anchor at `dispatch.py:40` | The symbol `_FORBIDDEN_REPO_ROOTS` is at line 43 today; and the stronger identity-based check is in `shared/coordinator/governed_core.py` | memory file and plan text cite line 40; line moved. |
| `boot_canary.py` "nothing calls this at boot yet; C1 wires it" | Still no non-test caller found by my search, although C1 shipped (`/coord` live 2026-07-15) | Card F; not yet confirmed by a live boot. |
| ADR-033 "PROPOSED ... Built DORMANT" | `[image_generation].enabled = true`, go-live 2026-06-16 | ADR-033 header versus default.toml line 327; header not yet replaced. |
| `docs/runbooks/battery_cadence_and_targeted_runs.md` (title "the 23:00 anchor") | DEC-14 (nightly battery cancelled indefinitely) | The runbook has no mention of DEC-14 (search); `docs/ROADMAP.md` still has 8 lines containing "23:00". The ROADMAP's STOP DOING item 1 already says a 23:00 wait is a habit. |
| "Memory: the machine-enforced version lives in `docs/performance/POLICY.md`" | The file is on an unmerged branch only | `C:/Users/mrbla/blarai-wt-perf-policy`; Card H. |
| `docs/learning/lessons_deck/README.md`: 126 units over 107 lessons | LESSONS.md indexes up to 385 | Deck currency not verified. |

---

## What I could not verify
- Every Vikunja ticket's current state and text (no call made). All ticket numbers are from the cited files.
- `docs/design/CODER_DEFINITION_OF_DONE.md` was read at its status lines, row 5, row 6 top, row 13, row 14 top, row 21 and the closing sections, not end to end (2,382 lines). Row statuses may have moved after their last dated line.
- B9 counts after 2026-08-30 and the figures in `CLAUDE.md` status_snapshot: cited, not recomputed.
- The corpus accuracy programme (#1616, #1641, #1648) beyond one memory file dated 2026-09-24, DEC-13, the extraction contract header, and the absence of its suite from main.
- `shared/coordinator/` beyond the module headers I read (`governed_core`, `boot_canary`, `policy`, `provenance`, `config` partly); the shadow journal contents; the born-encrypted proposal store.
- Whether tickets #865 to #868 (supervision) and #878 (dashboard) produced code: a keyword search found none.
- Contents of the learning decks, `docs/governance/*.html` reports, `evals/golden/coordinator.jsonl`, `docs/design/advanced_intake_*` beyond headers, ADR-019 and ADR-033 bodies, FIELD_NOTES beyond its size.
- Whether the WinUI app, the Desktop shortcuts or the voice and image paths work today; no application was started.
- The Hugging Face dataset and the agentic-setup run records (existence only).
- Path existence: I intended every path cited in this file to exist, and checked them with a script after writing (result reported in the hand-back).
