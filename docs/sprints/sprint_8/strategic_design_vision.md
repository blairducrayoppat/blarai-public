---
# Strategic Design Vision (SDV) — BlarAI Sprint 8
#
# Authored interactively by Co-Lead Architect + Lead Architect at sprint start.
# Baseline against which the end-of-sprint SCR and SWAGR measure success and gap.
---
sprint_id: 8
sprint_name: "Test Quality Remediation"
predecessor_sprint_id: 7
vikunja_tracking_task_id: 82
start_date: "2026-04-22"
target_completion_date: "2026-04-27"
la_approved_on: "2026-04-22T00:11:12-05:00"
la_approved_by: "blarai"
co_lead_drafted_on: "2026-04-22T00:07:00-05:00"
co_lead_commit_when_drafted: "4c97ce2"
sdv_version: 2
---

# Strategic Design Vision — Sprint 8: Test Quality Remediation

## 1. Executive brief

Sprint 8 closes all 45 test-quality gaps catalogued by the Sprint 7 audit in
`docs/TEST_AUDIT_FINDINGS.md` (13 HIGH / 24 MEDIUM / 8 LOW). This sprint exists because
Sprint 7's docs-only audit surfaced unverified decision boundaries across every service
cluster — the escalation-floor boundary in the Policy Agent (PA), config-validation gaps
in the Assistant Orchestrator (AO), zero coverage of the UAC elevation path in the launcher,
and structural placement violations that dilute the regression suite's diagnostic value.
We do it now, before any new use-case work begins, because the next EA to touch these
services will depend on the test baseline to catch regressions — and that baseline currently
has silent holes. Done = all 45 items addressed with a per-item disposition note in a
sprint-close comment on Vikunja #82, the regression suite still passing at its current
baseline after every EA merge, and no production file appearing in any EA's diff. Sprint 8
also debuts the full DEC-15 sprint lifecycle (SDV → SCR → SWAGR) for the first time.

The guiding principle for this sprint: **mature not minimal**. EA agents are expected to
build complete, robust test coverage — not the minimum that satisfies the item's literal
description. Adjacent findings discovered during EA work are in scope (within the 1-hour
per-item cap defined in §5.3).

## 2. Context

### 2.1 Predecessor sprint outcome

- Predecessor SCR: N/A — Sprint 7 predates DEC-15; no SCR was authored per LA direction
  2026-04-21.
- Predecessor SWAGR: N/A — no SCR to audit.
- Sprint 7 ("Audit Test Suite") was a docs-only qualitative audit (5 EAs, all merged to main
  by 2026-04-21, synthesis commit `46278a9`). Its sole strategic artifact is
  `docs/TEST_AUDIT_FINDINGS.md`, which is Sprint 8's complete input specification. Sprint 7
  left no open threads; all 5 EAs merged cleanly. The open items ISS-1 (AO speculative
  decoding), ISS-2 (think tags in TUI), and ISS-3 (PA classification misses) remain in the
  backlog; ISS-3 is explicitly out of scope for Sprint 8 per LA direction.

### 2.2 Repo state at kickoff

- Main branch HEAD: `4c97ce2`
- Most recent ledger entry: Entry 43
- Open Vikunja Pending-Human gates (Agent Gates bus, project 6): 0 — clean start
- Known-active feature branches: none (all Sprint 7 branches merged)
- Uncommitted working-tree files: 3 (`phase2_gates/evidence/uat2_milestone2_prompt_flow.json`,
  `phase2_gates/evidence/uat2_real_runtime_activation.json`,
  `tools/autonomy_budget/state.json`) — fleet idle-state artifacts, not blocking Sprint 8

### 2.3 External inputs driving this sprint

- **LA discovery session (2026-04-21)**: scoped Sprint 8 as pure test-authoring closure of all
  45 audit items; ISS-3 (PA stop-token fix) explicitly deferred.
- **DEC-15 (approved 2026-04-21)**: introduced sprint-level SDV/SCR/SWAGR lifecycle; Sprint 8
  is its first live run.
- **"Mature not minimal" directive (LA, 2026-04-22)**: EA agents are authorized to address
  directly adjacent findings discovered during their work, subject to a per-item cap of ≤ 1
  hour additional work. Findings exceeding the cap are flagged and opened as new Vikunja tasks.
- **Sprint Auditor HARD breach resolution (Vikunja tasks #61, #66, 2026-04-22)**: Sprint
  Auditor role registration resolved; Sprint 8 is the first sprint where the Sprint Auditor
  is expected to fire cleanly at sprint end.

## 3. Sprint purpose

Sprint 8 is a test-quality hardening sprint with a single strategic goal: close the gap
between what the system's tests claim to verify and what they actually verify. The Sprint 7
audit revealed that several critical behavioral invariants — the PA escalation-floor boundary,
the AO config-validation layer, the launcher's UAC elevation path, and the vsock topology
deployment gate — have no test that would catch a regression. These are not minor coverage
gaps; they are primary fail-closed mechanisms the system relies on for operational safety.

The next use-case development sprint will author new EAs that run against this test baseline.
An EA that hits a regression in `resolve_deployment_mode()` or the UAC elevation helper will
fail with a generic error rather than a direct diagnostic signal, causing wasted debugging
time and risk of misdiagnosis. By closing these gaps first, the fleet operates on a reliable
diagnostic foundation for all future work.

Sprint 8 also addresses structural debt from test placement violations: 23 live-TCP tests
currently running in unit-scope directories artificially inflate the REGRESSION suite's
runtime and can cause false deselection of tests that should be integration-scoped.
Correcting placement aligns the test suite with `docs/TEST_GOVERNANCE.md`'s marker taxonomy,
which future EAs are expected to follow.

If this sprint were skipped, the next production-touching EA would operate on a test baseline
with 13 HIGH-priority unverified paths. A single regression in any of them could pass CI
undetected and reach the operational system.

## 4. Success criteria

1. **All 45 audit items addressed**: Every item from `docs/TEST_AUDIT_FINDINGS.md` has a
   recorded disposition (new test authored, accepted with explicit rationale, or deferred
   with justification). *Verification: sprint-close comment on Vikunja #82 lists all 45
   items by disposition.*

2. **Regression baseline maintained after every EA merge**: `pytest shared/ services/
   launcher/ --tb=short -q` passes at ≥ 755 tests (2 skipped allowed) after each EA merges
   to main. *Verification: EA agents include passing test count in their commit message; LA
   confirms post-merge.*

3. **No production code changes**: No file outside `**/tests/`, `conftest.py`, `docs/`, and
   `pyproject.toml` appears in any EA's git diff against main. *Verification: `git diff
   main...<ea-branch> --name-only | grep -vE "tests|conftest|docs|pyproject"` returns empty.*

4. **Net new test count ≥ 30**: Total collected test count increases by at least 30 across
   the sprint. *Verification: compare `pytest --co -q` count pre-sprint vs. post-EA-4 merge
   (before EA-5's structural moves, which change no test logic).*

5. **Test collection intact after EA-5**: `pytest --co -q shared/ services/ launcher/
   tests/` completes with zero collection errors after EA-5 merges. *Verification: EA-5
   runs collection check as its first post-move validation step before any further work.*

## 5. Scope

### 5.1 In-scope

1. **Policy Agent cluster (EA-1)**: All `policy_agent` gap items from the audit —
   escalation-floor boundary test (confidence == 0.50); RateLimiter sliding-window time-based
   expiry test; `boot.py` exception-in-action path, `BootState.failed_step` property,
   `dev_mode` parameter effect, `retry_delay_s` non-default isolation; `entrypoint.py`
   `validate_runtime_config()` direct isolation, `stop()` isolation, `last_failure` error-code
   assertions added to all existing fail-closed tests; `car.py` string `sensitivity`
   normalization + `parameters_schema` propagation; `constants.py` direct assertion tests
   for all behavioral constants.

2. **Assistant Orchestrator + Semantic Router cluster (EA-2)**: PGOV leakage threshold exact
   boundary test (cosine_similarity == 0.85); SR dual-gate threshold exact-point tests
   (similarity == 0.50, margin == 0.04, margin == 0.03) via mock-controlled centroids and
   embeddings; AO `entrypoint.py` config-validation coverage (≥ 6 of the ~13 uncovered
   constraints, all 13 preferred under "mature not minimal"); AO `entrypoint.py` HEARTBEAT
   message handling + `stop()` isolation; `circuit_breaker.py` over-limit-token,
   simultaneous-trip, and `new_request()` reset tests; `pgov.py` CREDIT_CARD + HEX_SECRET
   PII pattern tests; `constants.py` direct assertion tests for AO and semantic_router;
   `pgov_display.py` `hide()` assertion fix (assignment → real assertion).

3. **UI Gateway + UI Shell cluster (EA-3)**: `session_panel.py` dedicated test file
   (SessionPanel public methods including async `to_thread()` wiring, `SessionListItem`
   label text format); `app.py` `action_submit_prompt()` PGOV-denied branch, PGOV-approved
   branch, RuntimeError/Exception handlers; boot poll attempt-marker progression (multiple
   loop iterations); `transport.py` `STREAM_TOKEN_BUFFER_LIMIT` overflow guard, `stream_tokens`
   malformed-message `continue` path, `check_pa_status` short-circuit test; `constants.py`
   direct assertion tests for ui_gateway and ui_shell.

4. **Shared + Launcher + Integration cluster (EA-4)**: `shared/runtime_config.py` full
   isolation (`resolve_service_root()` both normal and PyInstaller frozen branches,
   `resolve_deployment_mode()` three-tier precedence, `parse_deployment_mode()` normalization,
   `build_failure_fingerprint()` structure); `shared/schemas/car.py` dedicated test file
   (canonical_hash determinism under field permutation, `is_complete()` semantics,
   `DecisionArtifact` Pydantic validators, enum membership); `shared/ipc/protocol.py` six
   UI-gateway convenience encoder tests (regression-scope coverage); `launcher/__main__.py`
   HIGH-priority branches (prompt-flow preflight failure, `_run_uat2_prompt_flow_preflight()`
   isolation, `_cleanup()` atexit order and guards, `_vm_was_started` bookkeeping);
   `launcher/guest_deploy.py` HIGH-priority failure paths (`_validate_vsock_topology` all 8
   failure branches, `_validate_guest_runtime_configs` failure paths); `launcher/vm_manager.py`
   `request_elevation()` direct coverage.

5. **Cross-service structural cleanup (EA-5)**: Stale NPU nomenclature rename across PA +
   AO + integration test files (e.g. `_make_npu_stub()` → `_make_gpu_stub()` and all related
   identifiers); `jwt_minter` layering inversion fixes (2 import reversals); migration of 23
   live-TCP tests from unit-scope directories → `tests/integration/` with correct `slow`
   marker; migration of 19 non-cross-service tests from `tests/integration/` → respective
   service unit-test directories. **EA-5 internal execution order: (1) rename pass,
   (2) import fixes, (3) file moves last** — this sequencing minimizes merge-conflict risk
   and ensures rename correctness is verified before any file is relocated.

### 5.2 Out-of-scope (deliberately deferred)

1. **ISS-3: PA stop-token fix** — requires production code changes to `gpu_inference.py`,
   violating Sprint 8's pure test-authoring mandate. Deferred to a future sprint per LA
   direction 2026-04-21.
2. **New cross-service integration scenarios requiring live Hyper-V VMs** — tests requiring
   a running VM (AF_HYPERV socket path, real guest deployment) are not reproducible without
   hardware. Mock-based approach (as in existing `vm_manager.py` tests) is the accepted
   substitute; real-hardware paths deferred to a future Infrastructure sprint.
3. **USE-CASE-002/003/005 feature development** — no new service functionality this sprint.
4. **Production code cleanup or refactoring** — if an EA discovers a code smell, it documents
   it as a new finding in its completion report and does not fix it.
5. **Retroactive Sprint 7 SCR or SWAGR** — LA explicitly declined retroactive DEC-15 artifacts
   for Sprint 7 (2026-04-21 direction); Sprint 7 remains a pre-DEC-15 sprint in the record.
6. **Parallel EA execution** — all EAs execute sequentially to eliminate merge-conflict risk
   between EAs touching overlapping test files.

### 5.3 Scope boundaries and edge cases

- **"Mature not minimal" adjacent scope**: An EA may author tests for directly adjacent
  findings discovered during its work — even if not pre-listed in `TEST_AUDIT_FINDINGS.md`
  — provided each new item adds ≤ 1 hour of additional work. Items exceeding the cap are
  flagged in the EA's completion report and opened as new Vikunja tasks by the Co-Lead. This
  is not a license for unbounded scope expansion; it is a license to not artificially truncate
  a clearly related test case.
- **Items marked "N/A dead code" or "deferred to integration/hardware"**: Closed with an
  explicit rationale note. They count toward the 45-item closure total but do not require
  a new test. The sprint-close comment will list them by name with the disposition.
- **constants.py gap per cluster**: Each EA addresses the `constants.py` gap for its own
  service cluster(s). No shared constants EA; ownership follows the service-cluster boundary.
- **AO entrypoint config validation floor**: EA-2 must cover ≥ 6 of the ~13 uncovered
  constraints. Covering all 13 is encouraged under "mature not minimal" if each additional
  test is a straightforward parameterized case. EA-2 notes residual uncovered constraints
  in its completion report.
- **EA-5 enumeration gate (non-negotiable)**: SDO must require EA-5's comprehension gate to
  enumerate every file that will move — source path, destination path, and any conftest.py
  or `__init__.py` adjustments required — before any work proceeds. This is a harder gate
  than the standard comprehension gate and must be encoded explicitly in EA-5's prompt.

## 6. Deliverable summary

| Deliverable | Type | Target location | Success criterion |
|---|---|---|---|
| EA-1 test additions — policy_agent | test | `services/policy_agent/tests/` | #1, #2, #3 |
| EA-2 test additions — AO + semantic_router | test | `services/assistant_orchestrator/tests/`, `services/semantic_router/tests/` or `shared/tests/` | #1, #2, #3 |
| EA-3 test additions — ui_gateway + ui_shell | test | `services/ui_gateway/tests/`, `services/ui_shell/tests/` | #1, #2, #3 |
| EA-4 test additions — shared + launcher + integration | test | `shared/tests/`, `launcher/tests/`, `tests/integration/` | #1, #2, #3, #4 |
| EA-5 structural cleanup — rename + import fix + file moves | test (rename/move) | Various (enumerated in EA-5 comprehension gate) | #1, #2, #3, #5 |
| Sprint-close comment on Vikunja #82 | documentation | Vikunja task #82 comments | #1 |

## 7. EA milestone plan

| EA-# | Working title | One-sentence purpose | Depends on | Approx size |
|---|---|---|---|---|
| EA-1 | Policy Agent Test Hardening | Close all boundary, isolation, and constants coverage gaps in the policy_agent service cluster. | main (`4c97ce2`) | L |
| EA-2 | AO + Semantic Router Test Hardening | Close PGOV leakage-threshold boundary, SR dual-gate boundary, AO entrypoint isolation, and constants gaps in the AO and semantic_router clusters. | EA-1 merged | M |
| EA-3 | UI Gateway + UI Shell Test Hardening | Close all coverage gaps in ui_gateway and ui_shell, including the zero-coverage session_panel.py and app.py action-handler gaps. | EA-2 merged | M |
| EA-4 | Shared + Launcher + Integration Hardening | Close HIGH-priority gaps in shared (runtime_config, schemas/car), launcher (prompt-flow preflight, UAC elevation, guest_deploy topology gates), and integration protocol encoders. | EA-3 merged | M |
| EA-5 | Cross-Service Structural Cleanup | Rename stale NPU identifiers, fix jwt_minter import layering, and migrate misplaced tests to correct directories per TEST_GOVERNANCE.md taxonomy. | EA-4 merged | M |

**Sequencing rationale**: Each EA builds on the previous to avoid conftest conflicts. EA-5
executes last because it moves files; doing so earlier would cause path conflicts in EAs
that assume stable test-file locations. Within EA-4, HIGH-priority items (runtime_config,
guest_deploy, launcher preflight) must be addressed before MEDIUM items — SDO should encode
this priority ordering in EA-4's prompt.

## 8. Dependencies and prerequisites

### 8.1 Upstream dependencies

- `docs/TEST_AUDIT_FINDINGS.md` present on main — ✅ confirmed at kickoff
- `docs/TEST_GOVERNANCE.md` present on main — ✅ confirmed at kickoff
- All Sprint 7 EA branches merged to main — ✅ confirmed (synthesis `46278a9`)
- `sprint_auditor` role registered in autonomy budget config — ✅ resolved (tasks #61, #66)

### 8.2 External dependencies

- No external network dependencies (pure test-authoring sprint).
- Python + pytest environment assumed stable at current versions in `pyproject.toml`.
- Windows host required for EA agents to run `pytest --co` collection checks (EA-5 exit gate).

### 8.3 Assumed invariants

- Production source files (`shared/src/`, `services/*/src/`, `launcher/src/`) are frozen for
  the duration of Sprint 8. If any production code change is required to unblock a test, that
  is a scope exception requiring LA approval — it is not an EA decision.
- `docs/TEST_AUDIT_FINDINGS.md` is the complete and final Sprint 7 gap catalog. No new
  Sprint 7 findings should surface during Sprint 8 execution.
- The regression baseline of 755 passed / 2 skipped is stable at HEAD `4c97ce2`.

## 9. Risks and unknowns

### 9.1 Known risks

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| EA-5 file moves break test collection (missing `__init__.py`, wrong conftest, marker gap) | Medium | High | EA-5 comprehension gate must enumerate every move before proceeding; `pytest --co` is exit gate |
| EA-4 HIGH items (launcher UAC elevation, prompt-flow preflight) require complex isolation patterns that push EA-4 to L size | Medium | Medium | SDO flags sizing concern at comprehension gate; Co-Lead upgrades EA-4 to L if confirmed |
| AO entrypoint config validation has ~13 constraints — EA-2 may address fewer than all under M sizing | Low | Low | SDV §5.3 floors at ≥ 6; EA-2 completion report notes residual uncovered constraints |
| Sprint Auditor first live firing identifies SWAGR gap mid-sprint | Low | Low | SWAGR is non-blocking by design (DEC-15); LA reads post-sprint |
| "Mature not minimal" adjacent scope causes EA to expand unexpectedly | Low | Medium | Hard 1-hour cap per new item enforced via SDO comprehension gate; excess flagged, not absorbed |

### 9.2 Known unknowns

1. Exact net new test count — depends on how many discrete assertions each gap item requires
   (some items yield 1 test; others like AO entrypoint config constraints may yield 5–10).
2. Whether EA-4's `_run_uat2_prompt_flow_preflight()` isolation can be achieved without a
   running AO/PA instance — expected yes via heavy mocking, but the fixture pattern may need
   to be invented.
3. Whether any of the 23 TCP tests migrated by EA-5 have implicit dependencies on unit-scope
   conftest fixtures that don't exist in `tests/integration/`.

### 9.3 Unknown unknowns posture

Sprint 8 is test-only work with no production code changes, substantially reducing the
unknown-unknowns surface. The primary category of surprise is infrastructure: a test that
looks straightforward may require a fixture pattern that doesn't exist yet, or a file move
may expose a circular import. Under the "mature not minimal" directive, EA agents are
licensed to invest the extra hour to solve these cleanly — but they must surface surprises
to the SDO in their completion report rather than silently absorbing scope. The fleet's
peer-review lattice (EA → SDO → Co-Lead) is the primary detection mechanism for surprises
that exceed an EA's authority.

## 10. Alignment to long-term roadmap

- **Project phase alignment**: Phase 5 Post-Operational Development. Sprint 8 is the first
  sprint of the test-governance hardening workstream that the Sprint 7 audit opened.
- **Use Case alignment**: Touches all service clusters and thus all 9 Use Cases indirectly.
  Most directly relevant to USE-CASE-001 (PA boundary tests), USE-CASE-004 (AO config
  validation + PGOV), and the launcher/deployment infrastructure that underlies every use case.
- **ADR alignment**: No ADR changes. EA-5's NPU → GPU rename pass in test files confirms
  ADR-011 (GPU-only inference) at the test-artifact level. EA-2's PGOV threshold boundary
  test confirms ADR-012 §2.4 (thinking mode strategy) by verifying the cosine threshold
  that governs output governance.
- **DEC alignment**: DEC-15 (sprint lifecycle) — Sprint 8 is the first live run of the full
  SDV → SCR → SWAGR pipeline. DEC-12 (EA prompt review lattice) — no changes; standard
  operation. DEC-11 (autonomy budgets) — no changes.

## 11. Roles and accountability

| Role | Responsibility this sprint | Budget |
|---|---|---|
| LA (Lead Architect) | SDV sign-off, CAR adjudication if scope exceptions arise, SWAGR read at sprint end | ~20 min total: 15 min SDV, 5 min SWAGR read |
| Co-Lead Architect | SDO continuation XML authoring, EA prompt review via DEC-12 gate, SCR authoring at sprint end | Autonomous per DEC-11 §1.1 |
| SDO | EA prompt authoring (5 prompts, with tighter EA-5 gate), EA work peer review | Autonomous per DEC-11 §1.2 |
| EA Code | Milestone execution (5 EAs) | Autonomous per DEC-11 §1.3 |
| Sprint Auditor | SWAGR independent production post-SCR | Autonomous per DEC-15 §sprint_auditor_role_spec |

## 12. Estimated effort

- Rough duration: 3–5 calendar days (fleet-time), 5 EA milestones. L-sized EA-1 is the
  longest; M-sized EA-4 carries the most structural complexity and may prove L in practice.
- LA active-time expectation: ~20 min total across the sprint (SDV sign-off, SWAGR read at
  sprint end). EA merges are auto-merged by Co-Lead under `trusted_scope` mode (DEC-11 §3.4);
  no per-merge LA gate fires unless a merge fails the trusted-scope criteria.
- Confidence in estimate: **medium** — EA-4 (launcher isolation patterns) and EA-5 (42 file
  moves + conftest adjustments) are the primary sizing unknowns. If either escalates to L,
  add 1–2 days to the estimate.

## 13. Deliberate non-goals

1. **ISS-3 (PA stop-token mismatch)** — **Rejected because** it requires production code
   changes to `gpu_inference.py`, violating the pure test-authoring mandate. A future sprint
   addresses ISS-3 once the test quality foundation is solid.
2. **New integration tests requiring live Hyper-V VMs** — **Rejected because** the test
   environment constraint makes such tests non-reproducible for EA agents. Deferred to a
   future Infrastructure sprint.
3. **Production code cleanup discovered during EA work** — **Rejected because** introducing
   production changes mid-sprint creates audit complexity and regression risk. EA agents
   document and flag, then move on.
4. **Retroactive Sprint 7 SCR or SWAGR** — **Rejected per LA direction (2026-04-21)**;
   Sprint 7 remains a pre-DEC-15 sprint in the permanent record.
5. **Parallel EA execution** — **Rejected** to eliminate merge-conflict risk across EAs
   that touch overlapping test files and conftest fixtures. Sequential execution is not a
   bottleneck given fleet cadence.

## 14. Sign-off

### Lead Architect

> I, `blarai`, have reviewed this SDV on `<date>`. I approve the sprint scope, success
> criteria, and risk posture as stated. I accept that the fleet will proceed autonomously
> per the DEC-11 budgets within these bounds. I will read the SCR and SWAGR when produced.

_(Signed via the frontmatter field `la_approved_on` above. A commit authored by LA on main
is the durable signature.)_

### Co-Lead Architect

> Co-Lead acknowledges the LA-signed SDV and will translate it into the first SDO
> continuation XML + milestone sequencing per the DEC-12 flow. Any scope deviation arising
> during execution will be flagged via the DEC-12 peer-review lattice or escalated via a CAR.

_(Signed via the frontmatter field `co_lead_drafted_on` + git commit by [agent:co_lead]
that lands this SDV on main.)_

---

## Appendix A — SDV revision log

| Version | Date | Changed by | Change summary |
|---|---|---|---|
| 2 | 2026-04-22 | Co-Lead | Corrected §11 and §12: removed LA merge-approval responsibility; DEC-11 §3.4 `trusted_scope` mode is active — Co-Lead auto-merges EA branches |
| 1 | 2026-04-22 | Co-Lead | Initial draft |
