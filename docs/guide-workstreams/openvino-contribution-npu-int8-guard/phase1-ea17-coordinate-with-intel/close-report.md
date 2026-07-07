# EA-17 Phase 1 close report

**Workstream**: openvino-contribution-npu-int8-guard
**Phase**: 1
**Guide**: #11
**EA**: EA-17
**Authored**: 2026-05-12

## 1. Verdict

**PASS_WITH_NOTES**.

PASS rationale: all four artifacts produced per dispatch §scope/acceptance;
all preflight checks 0a-0i executed; fleet paused before branch checkout
and resumed after content commit; no GitHub posts; no BlarAI runtime
edits; no OpenVINO clone; no code patches.

WITH_NOTES rationale: three deviations from the dispatch as written —
all documented in §5 Anomalies. None affect deliverable correctness; all
informational for Guide-#11 cross-verification.

## 2. Preflight results

| Check | Result | Detail |
|---|---|---|
| 0a (fleet pause) | PASS_WITH_NOTE | `state.pause_fleet(...)` invoked on `devplatform/tools/autonomy_budget/state.json` (canonical state path); pause record commit `c58261a` on `devplatform/main`. **Note**: dispatch §preflight 0a referenced path `C:/Users/mrbla/BlarAI/tools/autonomy_budget/state.json`, which does not exist on disk. The canonical state file lives in devplatform, not BlarAI. Used the correct path. Anomaly A-NEW1. |
| 0b (working tree clean) | PASS_WITH_NOTE | BlarAI working tree clean at branch creation (`git status` confirmed). **Note**: devplatform had pre-existing uncommitted drift on `.mcp.json`, three scheduled-task xmls, two flag files, and state.json (timestamp-only). The drift is pre-existing fleet operations, not EA-17 work. Pause commit on devplatform staged only `tools/autonomy_budget/state.json`; other drift remains uncommitted. Anomaly A-NEW2. |
| 0c (required-tier prior-art reads) | PASS | Read in full: `docs/OPENVINO_CONTRIBUTION_PLAN_MARCH_2026.md`, `docs/ISSUE_34450_COMMENT_EDIT.md`, `docs/PR_34617_DESCRIPTION_PASTE.md`, `docs/PR_PACKAGE_ISSUE_34617.md`. |
| 0d (PR #34651 live state) | PASS_WITH_NOTE | Verified open, no Intel reviewers, 0 reviews. **Delta from dispatch §B2**: last activity 2026-04-24 (force-push / merge commit), not 2026-04-16 as dispatch claimed. 8-day delta. Anomaly A-NEW3. |
| 0e (issue #35641 live state) | PASS | Verified open, 0 comments, no Intel response. Assignees, labels, opened-date all match dispatch §B1. |
| 0f (issue #34450 closure mechanism) | PASS_WITH_NOTE | Verified closed; closure mechanism **not surfaced** in WebFetch summary; Intel response to the LA's catchable-error suggestion **not visible**. Per dispatch §execution/T1 MUST-NOT clause, engagement comment cites PR #34651 only — does NOT cite #34450 as resolution precedent. |
| 0g (state of #34532, #34617, npu_compiler #265+#266) | PASS_WITH_NOTE | Live state captured. **Delta from charter §5**: issue #34532 is closed, not "open, triaged" as charter says. Documented in `upstream-state-report.md` §4. Anomaly A-NEW4 (low-severity charter drift). |
| 0h (CONTRIBUTING.md + AI Usage Policy in full) | PASS | Read `CONTRIBUTING.md`, `CONTRIBUTING_PR.md`, `AI_USAGE_POLICY.md`, `.github/pull_request_template.md`. AI Usage Policy last modified 2026-02-20 (commit `c4f4325`) — **same text** that was in effect when PR #34651 was opened on 2026-03-12. No policy delta. No DCO sign-off required. |
| 0i (CLA status for `blairducrayoppat`) | PASS_WITH_NOTE | No CLA bot status visible on PR #34651's checks page; PR has been open since 2026-03-12 (\~62 days) without a CLA block surfacing. Inference: CLA is signed or the project does not gate on a CLA bot. Documented in `cla-and-ai-policy-brief.md` §1. |

## 3. Task results

### T1 — Engagement comment draft for issue #35641

- **Path**: `phase1-ea17-coordinate-with-intel/engagement-comment-draft.md`
- **Length**: 243 words in paste-ready comment body (within 150-250 band)
- **Key authoring choices**:
  - **No #34450 citation** — preflight 0f showed #34450 closed without
    Intel response visible. Per dispatch §execution/T1 MUST-NOT clause,
    engagement comment cites PR #34651 only.
  - **Three options offered, fourth implicitly invited** — closing
    line "happy to follow whichever direction fits best, or to adapt to
    a different approach" preserves Intel's freedom to propose a
    different shape. Suggestions, not demands, per acceptance criterion 1.
  - **Single @-mention: `@Zulkifli-Intel`** — selected over
    `@diego-villalobos` and `@Munesh-Intel` because Zulkifli-Intel is
    listed first among assignees on issue #35641 (suggesting primary
    triage ownership) and Munesh-Intel already carries PR #34651 plus
    other related assignments. LA may rotate before posting.
  - **AI Assistance block inline at end of comment body, two short
    sentences** — mirrors `PR_34617_DESCRIPTION_PASTE.md` §AI Assistance
    structure adapted for the comment scenario. Honest dual-tool
    attribution (Copilot for issue body, Claude for comment) per AI
    Usage Policy "Disclose significant AI assistance".
  - **No code, no PR speculation, no "you haven't reviewed" framing**
    — per dispatch §execution/T1 MUST-NOT clauses.
  - **Neutral opener "Following up on this issue"** — no commendations,
    per BlarAI memory note "No commendations of agents".

### T2 — CLA + AI Usage Policy compliance brief

- **Path**: `phase1-ea17-coordinate-with-intel/cla-and-ai-policy-brief.md`
- **Key authoring choices**:
  - **CLA finding**: active (inferred from absence of bot block on
    PR #34651). Method of verification documented; uncertainty documented;
    fallback recovery procedure documented.
  - **AI Usage Policy excerpts verbatim**: suggested disclosure format,
    core contributor responsibilities, prohibited practices, enforcement
    basis, PR-template AI section, commit-message conventions (none
    mandated).
  - **Disclosure template for eventual #35641-fix PR**: paste-ready
    `### AI Assistance:` block adjusted for #35641 specifics and
    expanded dual-tool attribution (Copilot + Claude vs. PR #34651's
    Copilot-only disclosure).
  - **No DCO sign-off required**: verified via `CONTRIBUTING.md`,
    `CONTRIBUTING_PR.md`, PR template, and PR #34651's commit history.
  - **No deltas**: AI Usage Policy commit `c4f4325` (2026-02-20)
    predates PR #34651 (2026-03-12). Same text in effect today.

### T3 — Upstream state report

- **Path**: `phase1-ea17-coordinate-with-intel/upstream-state-report.md`
- **Key authoring choices**:
  - **Per-target state tables** for PR #34651, issues #34617 / #34450 /
    #34532 / #35641, npu_compiler PRs #265 + #266 — with fetch timestamps
    and dispatch-delta callouts.
  - **LA-facing portfolio recommendations**: Phase 1 immediate actions,
    Phase 1 deferred items (hardening followups per ack n5), Phase 1
    NON-recommendations.
  - **Critical strategy finding**: npu_compiler PRs #265+#266 received
    actual Intel reviewer engagement (`andrey-golubev` requested changes)
    — strengthens the engagement posture; PR #34651's stall is reviewer-
    pool-specific, not author-specific.

## 4. State findings

Fetch timestamps: all WebFetch calls in 2026-05-12 session, between
approximately 15:23Z (pause commit) and 15:50Z (T1 authoring).

| Target | Type | State | Last activity | Notes |
|---|---|---|---|---|
| openvino#35641 | issue | open | 2026-05-01 | 0 comments; no Intel response; assignees diego-villalobos / Zulkifli-Intel / Munesh-Intel; labels PSE, bug, support_request |
| openvino#34651 | PR | open | **2026-04-24** | No Intel reviewers; 0 reviews; 0 approvals; CLA bot not surfaced; labels `category: NPU`, `ExternalPR`; 2 commits |
| openvino#34617 | issue | open | 2026-03-10 | Closure target of PR #34651 (`Closes #34617`) |
| openvino#34450 | issue | **closed** | unknown (closure date not surfaced) | Closure mechanism not visible in WebFetch summary; no Intel response to catchable-error suggestion visible |
| openvino#34532 | issue | **closed** | 2026-03-06 | Charter §5 says "triaged"; live shows closed (drift) |
| npu_compiler#265 | PR | open | 2026-04-17 | andrey-golubev requested changes (root-cause vs symptom guard) |
| npu_compiler#266 | PR | open | 2026-04-17 | Same reviewer feedback class as #265 |

## 5. Anomalies

| ID | Description | Disposition |
|---|---|---|
| **A-NEW1** | Dispatch §preflight 0a path `C:/Users/mrbla/BlarAI/tools/autonomy_budget/state.json` does not exist. Canonical state file is `C:/Users/mrbla/devplatform/tools/autonomy_budget/state.json` per `devplatform/tools/autonomy_budget/state.py` `DEFAULT_STATE_PATH`. EA used the correct devplatform path. Same incorrect BlarAI-prefixed path appears in `devplatform/docs/governance/fleet-hygiene.md` §R7 example invocation. Doc fix required. | **Hardening followup** (Stage 6.7.5-style): update `devplatform/docs/governance/fleet-hygiene.md` §R7 and the EA-17 dispatch's preflight 0a / fleet_unpause snippets to use the canonical devplatform path. NON-OPTIONAL per ack n5. Vikunja ticket recommended. |
| **A-NEW2** | Devplatform working tree was not clean at preflight 0b — pre-existing uncommitted drift on `.mcp.json`, `tools/scheduled-tasks/wake-co_lead_architect.xml`, `wake-ea_code.xml`, `wake-sdo.xml`, `tools/fleet_observability/critical_pending.flag`, `tools/fleet_observability/vikunja_down.flag`, and state.json (timestamp-only). Pause commit explicitly added only `tools/autonomy_budget/state.json`. Other drift remains uncommitted. | Informational only. The drift predates EA-17 and is not EA-17's to clean. Surfaced to LA for awareness. Possibly worth a Vikunja ticket if it persists across sessions. |
| **A-NEW3** | Dispatch §B2 stated PR #34651's last activity was 2026-04-16. Live WebFetch shows 2026-04-24 (force-push / merge commit). 8-day delta. | Informational. Documented in `upstream-state-report.md` §1. No impact on engagement-comment correctness — comment does not cite the specific date. |
| **A-NEW4** | Workstream charter §5 lists openvino#34532 as "open, triaged". Live WebFetch shows **closed** (last activity 2026-03-06). Closure mechanism not surfaced in WebFetch summary. | **Hardening followup**: update charter §5 to reflect closed state at next charter edit. Stage 6.7.5-style. NON-OPTIONAL per ack n5. Note: appended-only by Guide-#11 per dispatch §constraints C-NOEDIT — EA-17 does not edit the charter; Guide-#11 picks this up at Phase 1 verdict authoring. |

**Anomalies that did NOT occur**: PR #34651 has not been reviewed,
merged, or assigned reviewers since 2026-04-24 (so no Phase 1 framing
restart per dispatch §execution/pf1_bifurcation); issue #35641 has
received no Intel comments since open (so the comment initiates rather
than responds); AI Usage Policy has not been amended since 2026-02-20
(so no disclosure-template regeneration needed).

## 6. Backlog math

- **Pre-Phase-1 Vikunja backlog**: 1 open ticket — Vikunja task #443
  (workstream parent, project 3, "Guide Workstream: OpenVINO #35641 —
  NPU INT8 Construct-Time Guard (Guide-#11)").
- **Post-Phase-1 expectation** (per dispatch §guide_verification/backlog_expectation):
  1 open ticket (#443 — parent stays open until full workstream closure)
  + 0-3 hardening tickets per ack n5.
- **Post-Phase-1 actual**: EA-17 surfaces **4 hardening-followup
  candidates** (3 from anomalies + 1 portfolio-side recommendation),
  exceeding the "0-3" expectation. **All NON-OPTIONAL per ack n5** —
  flagged here for Guide-#11 to bind to Vikunja at verdict authoring:
  1. Update `devplatform/docs/governance/fleet-hygiene.md` §R7 path
     reference + EA-17 dispatch path reference (A-NEW1).
  2. Update workstream charter §5 to reflect #34532 closed (A-NEW4).
  3. Verify issue #34450 closure mechanism (out of workstream scope per
     charter §2; separate small ticket).
  4. Fence-post fix in dispatch §B1 (11 vs 12 days) — trivial doc cleanup
     when next dispatch / next workstream-doc edit is authored.

  **Rationale for exceeding 0-3 expectation**: three of the four items
  are documentation drift discovered during preflight verification —
  i.e., they are exactly the class of "doc cleanup" item that ack n5
  designates NON-OPTIONAL. The Guide may triage priority but not
  existence.

## 7. Forward-looking notes for Phase 2

Per dispatch §close_report_format §7, Phase 2 recommendations based on
Phase 1 findings:

1. **Phase 2 cannot start until the engagement comment receives a
   substantive Intel response** (or the workstream's deferral window
   2026-07-01 passes). Phase 2 in the charter sketch is "build
   environment setup + NPUW LLM construct-path recon", but the *shape*
   of that work depends on Intel's steer:
   - If Intel says "extend PR #34651", Phase 2 sets up environment +
     locates the IR-introspection insertion point in the same `plugin.cpp`
     compile_model() flow PR #34651 already modifies. Branch should be
     based on the PR #34651 branch.
   - If Intel says "separate companion PR", Phase 2 sets up environment
     + locates the same insertion point + drafts a new branch from
     master.
   - If Intel says "defer", Phase 2 is paused.
   - If Intel proposes a fourth shape (e.g., "the IR exporter should
     refuse to produce INT8 weight-only for NPU targets at export
     time"), Phase 2's target subsystem moves to `optimum-intel` or
     `openvino.genai` rather than `intel_npu/plugin`.

2. **Build environment requirements surfaced in CONTRIBUTING.md
   reads** (preflight 0h): the OpenVINO source build is documented in
   `CONTRIBUTING.md` linked guides. Phase 2 dispatch should include
   live links to the current build-from-source guide and a sanity
   check of disk-space + toolchain requirements (Windows 11 host,
   Visual Studio 2022, CMake, Python, OpenCL/Level Zero runtimes for
   the NPU plugin's tests). The dispatch may also pre-flag the
   long-pole steps (cloning + sub-module init + initial cmake
   configure are 30+ min wall-clock items).

3. **Reviewer engagement is reviewer-pool-specific**, not author-blocked.
   npu_compiler PRs #265+#266 received `andrey-golubev` review feedback
   on 2026-04-17 — same author as PR #34651, different reviewer pool,
   actual engagement. Phase 1 engagement on issue #35641 may catalyze
   review on PR #34651 too (if Intel chooses option (a)), but should
   not depend on it. Phase 2's planning should treat PR #34651's
   merge-readiness as a separate, parallel concern.

## 8. Commit SHAs

| Commit | Repo | Branch | SHA | Description |
|---|---|---|---|---|
| Pause | devplatform | main | `c58261a` | `[agent:ea17] chore: pause fleet -- EA-17 phase1 openvino-35641 engagement work` |
| Content | BlarAI | feature/p-openvino-35641-phase1-engagement | *pending — appended when commit completes* | `[agent:ea17] phase1: openvino-35641 engagement artifacts` |
| Resume | devplatform | main | *pending — appended when commit completes* | `[agent:ea17] chore: resume fleet -- EA-17 phase1 engagement work complete` |

(Final SHAs are inserted into this section at the report's amend step
after content commit and resume commit land. If Guide-#11 needs the
authoritative SHAs before this report is amended, they are also in the
git log of the relevant branches and in the EA-17 final-response section
"E. Commit SHAs".)

## 9. AI usage in this phase

The EA agent itself is the AI assistance. This phase produced text
artifacts authored by an AI agent (the EA) under Guide-#11 supervision,
with LA approval gate on dispatch and verdict. State this verbatim; do
not synthesize.
