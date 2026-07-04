# Upstream state report — LA-facing

**Purpose**: a single page the LA can scan to understand the live state
of every upstream-engagement target adjacent to issue #35641, and where
each target sits in the contribution portfolio. **For LA only** — not
for inclusion in any Intel-facing artifact.

**Verification timestamp**: 2026-05-12 (preflight 0d-0g, this session).

**Terminology**: openvino#35641 is the **issue** the workstream targets;
openvino#34651 is the **precedent PR**. No conflation.

---

## 1. PR openvino#34651 — "[NPU] Early guard for unbounded dynamic shapes in `compile_model`"

| Field | Value |
|---|---|
| URL | https://github.com/openvinotoolkit/openvino/pull/34651 |
| Type | PR (pull_request) |
| State | **Open** (not merged) |
| Author | `blairducrayoppat` (the LA) |
| Opened | 2026-03-12 |
| Last activity | **2026-04-24** (force-push / merge commit) — **8 days later than the dispatch's §B2 estimate of 2026-04-16** |
| Commits | 2 |
| Base | `openvinotoolkit:master` |
| Head | `blairducrayoppat:fix/npu-unbounded-dynamic-shape-guard` |
| Reviewers | None assigned |
| Assignees | None |
| Reviews received | 0 |
| Approvals | 0 |
| Requested changes | 0 |
| Labels | `category: NPU`, `ExternalPR` |
| Milestone | None |
| CLA bot | No CLA bot status visible (see compliance brief §1) |
| CI status | Not visible in WebFetch — appears to be pending NPU-team workflow approval |
| Closes | issue #34617 (`Closes #34617`) |

**Delta from dispatch §B2**: dispatch claimed last activity 2026-04-16
(author rebase + review request). Live state shows 2026-04-24
(force-push / merge commit) — **8-day delta**, attributed to either a
follow-up rebase or a fast-forward sync with master that I cannot
distinguish from the WebFetch summary. Either way, no Intel-side activity
on the PR; the author has continued maintaining the branch.

**LA action options on PR #34651**:

- **A — Status quo (recommended for Phase 1)**: PR #34651 stays as-is.
  The issue #35641 engagement comment cites the PR as precedent context.
  Intel's response to issue #35641 is the steering signal.
- **B — Sync with master only**: if the branch has drifted, a no-content
  rebase + force-push refreshes the commit timestamp but is unlikely to
  attract a reviewer that hasn't already engaged. Low value.
- **C — Quiet revive (NOT recommended via this workstream)**: a ping
  on PR #34651's own thread is explicitly out of scope per the
  charter §2 ("Reviving PR #34651 itself ... If the topic surfaces during
  engagement, surface to LA; do not unilaterally re-ping or restructure
  PR #34651").
- **D — Withdrawal (NOT recommended)**: withdrawing PR #34651 would
  remove the precedent the issue #35641 engagement depends on.

**LA decision points**:

1. None for Phase 1. The PR stays untouched.
2. If Phase 1 yields no Intel response on issue #35641 by the workstream's
   deferral window (2026-07-01 per charter §6), the escalation path
   (Intel DevHub Discord, GitHub Discussions) becomes available — but
   that's a Phase-1+ outcome decision, not a Phase 1 action.

---

## 2. Issue openvino#34617 — NPU `compile_model` fails with "to_shape was called on a dynamic shape" for Qwen3-0.6B INT4

| Field | Value |
|---|---|
| URL | https://github.com/openvinotoolkit/openvino/issues/34617 |
| Type | issue |
| State | **Open** |
| Opened | 2026-03-10 |
| Last activity | 2026-03-10 (the WebFetch summary did not surface any activity since open, but this is a long-tail signal — the issue may have triage activity not surfaced in the brief) |
| Reporter | `blairducrayoppat` (the LA) |
| Relationship to PR #34651 | **Closure target** — PR #34651's description says `Closes #34617`. Merging PR #34651 auto-closes this issue. |

**Implication for Phase 1**: issue #34617 is the precedent's closure
target; it is NOT itself an engagement target. State checks only. The
issue remains open because the PR is open; no LA action.

---

## 3. Issue openvino#34450 — NPU compiler SIGABRT on degenerate tensor shapes

| Field | Value |
|---|---|
| URL | https://github.com/openvinotoolkit/openvino/issues/34450 |
| Type | issue |
| State | **Closed** |
| Opened | 2026-03-03 |
| Reporter | `blairducrayoppat` (the LA) |
| Assignees (at close) | Munesh-Intel, YuChern-Intel, diego-villalobos |
| Closure mechanism | **Not visible** in the WebFetch summary — the page does not surface "closed by PR" / "not planned" / "completed" disposition. |
| Intel response to catchable-error suggestion | **None visible**. The LA's comment in `docs/ISSUE_34450_COMMENT_EDIT.md` suggested the catchable-error pattern and cross-referenced npu_compiler PRs #265+#266; no Intel engineer response is surfaced. |

**Critical finding for engagement comment**: per dispatch §execution/T1
MUST-NOT clause, "If 0f shows #34450 was closed without engagement,
REMOVE [the #34450 citation]; rely solely on PR #34651 as the precedent."

**→ Acted on**: the engagement-comment-draft.md does NOT cite #34450 as
a resolution precedent. Only PR #34651 is cited.

**LA action**: optional — if the LA wants a definitive answer on #34450's
closure mechanism, navigating to the issue page directly (webUI) will
surface the closure event in the timeline (closed-by-X). This is not
required for Phase 1 deliverables.

**Hardening followup candidate (ack n5)**: there is value in posting
a brief follow-up comment on issue #34450 asking how Intel resolved it,
if only for future-evidence purposes. **NOT in Phase 1 scope** (charter
§2 excludes engagement on issues other than #35641); flagged here for
LA disposition. Vikunja followup ticket recommended below in §7.

---

## 4. Issue openvino#34532 — GPU ScatterUpdate precision + Loop-body crash

| Field | Value |
|---|---|
| URL | https://github.com/openvinotoolkit/openvino/issues/34532 |
| Type | issue |
| State | **Closed** — *deviation from dispatch §B3-adjacent assumption that this issue was open / triaged with last activity tracked separately* |
| Last activity | 2026-03-06 (per WebFetch) |
| Assignees | Munesh-Intel, Wan-Intel, jgespino |
| LA prior engagement | Posted diagnostic comment with Arc 140V (Xe2) confirmation evidence; see `docs/OPENVINO_CONTRIBUTION_PLAN_MARCH_2026.md` §"Completed Work" |

**Delta from charter assumption**: the workstream charter §5 lists
#34532 as "open, triaged". Live state shows **closed**. The closure
mechanism is not surfaced in the WebFetch summary. Possibilities:

- Closed as "not reproducible" / "won't fix" / "duplicate".
- Closed by an internal Intel fix that landed in 2026.1 (the dispatch's
  source notes did not flag a `2026.1` release with this fix).
- Auto-closed by stale-bot.

**LA action options**:

- None mandatory for the #35641 engagement.
- Optional: navigate to the issue webUI to inspect closure event for the
  LA's portfolio-tracking benefit.

**Hardening followup candidate (ack n5)**: Vikunja ticket — verify
#34532 closure mechanism and update charter §5 / workstream
documentation to reflect closed state. Recommended below in §7.

---

## 5. Issue openvino#35641 — primary engagement target (INT8 weight-only NPU silent-construct crash)

| Field | Value |
|---|---|
| URL | https://github.com/openvinotoolkit/openvino/issues/35641 |
| Type | issue |
| State | **Open** |
| Opened | 2026-05-01 |
| Reporter | `blairducrayoppat` (the LA) |
| Assignees | diego-villalobos, Zulkifli-Intel, Munesh-Intel |
| Labels | PSE, bug, support_request |
| Comments | 0 |
| Intel engineer comments | **None observed** as of 2026-05-12 (12 days since filing) |
| Last activity | 2026-05-01 (issue open; no further activity) |

**Delta from dispatch §B1**: dispatch claimed "0 Intel response observed
as of 2026-05-12 (11 days since filed)". Live state confirms — still 0
Intel responses; 12 days at re-verification (one day off because the
dispatch was authored on 2026-05-12 and recheck is also 2026-05-12,
arithmetic-wise the issue was opened 2026-05-01 so 11 days at dispatch
authoring is correct, 12-day characterization here is fence-post).

**Implication**: the engagement comment in
`engagement-comment-draft.md` is a clean first-touch — there is no
existing Intel response to react to. The comment initiates engagement;
it does not respond.

---

## 6. npu_compiler PRs #265 and #266 — INT4 grouped-quant degenerate-shape guards

### 6a. npu_compiler PR #265

| Field | Value |
|---|---|
| URL | https://github.com/openvinotoolkit/npu_compiler/pull/265 |
| Type | PR |
| State | **Open** |
| Last activity | 2026-04-17 |
| Title | NPU compiler guard in `ConvertFCToConv` for zero-channel FC ops |
| Reviewer engagement | **andrey-golubev requested changes** — advocates fixing root cause rather than guarding the symptom. Contributor (the LA) acknowledged this is interim defense-in-depth pending investigation. |

### 6b. npu_compiler PR #266

| Field | Value |
|---|---|
| URL | https://github.com/openvinotoolkit/npu_compiler/pull/266 |
| Type | PR |
| State | **Open** |
| Last activity | 2026-04-17 |
| Title | NPU compiler guard in `UnrollFullyConnected` for zero/negative FC dimensions |
| Reviewer engagement | Awaiting approval; reviewer feedback indicates root-cause fix preferred over downstream-pass guard. |

**Critical finding**: both PRs have **actual Intel reviewer engagement**
(andrey-golubev). This is the strongest signal in the LA's portfolio
that Intel reviewers do engage with this contributor's PRs given enough
time and the right plugin layer.

**Implication for engagement strategy on issue #35641**:

- PR #34651's stall is not endemic — it is specific to the
  `intel_npu/plugin` layer where YuChern-Intel / Munesh-Intel have not
  yet engaged. The npu_compiler subsystem (`andrey-golubev`) is a
  different reviewer pool.
- This **strengthens** the Phase 1 engagement posture: Intel reviewers
  DO engage; the issue #35641 comment may just be the catalyst the NPU
  plugin reviewers need to start review on the precedent PR #34651 too.

**LA action options**:

- **A — Status quo (recommended for Phase 1)**: leave both PRs as-is.
  The reviewer-requested-changes thread is the LA's to address on its
  own cadence; outside this workstream's scope.
- **B — Address andrey-golubev's feedback**: investigate the root-cause
  pass that produces zero-dim tensors and refactor the PRs to fix root
  cause. **Significant effort** (out of Phase 1 scope; possibly out of
  workstream scope).
- **C — Withdraw and replace**: only if root-cause investigation reveals
  the guards are inferior to a different approach.

**Hardening followup candidate (ack n5)**: Vikunja ticket — address
andrey-golubev's review feedback on PRs #265 + #266. **NOT in this
workstream's scope**; this is its own contribution-track work.
Recommended below in §7.

---

## 7. Recommendations for LA

### 7a. Phase 1 immediate actions (LA-side)

- [ ] Review the engagement-comment-draft.md content + AI Assistance
      block (T1).
- [ ] Review the CLA + AI Policy compliance brief (T2).
- [ ] Decide on the single @-mention in the comment closing (current:
      `@Zulkifli-Intel`; LA may rotate to `@diego-villalobos` if
      relationship preference warrants).
- [ ] Post comment on issue #35641 via GitHub webUI.
- [ ] Record posted-comment URL in `STATUS.md` under Phase 1 entry.

### 7b. Phase 1 deferred items (hardening followups, ack n5)

Per BlarAI memory note "Hardening followups are NON-OPTIONAL (doc +
architectural)", all items below are recommended for Vikunja staging
under the workstream parent task #443. LA may triage priority but
existence is non-optional.

1. **Verify #34450 closure mechanism + Intel response status**. Method:
   navigate to issue webUI, inspect timeline. Optionally post a single
   polite comment asking how Intel resolved it. **Out of this
   workstream's scope** (charter §2 excludes engagement on issues other
   than #35641). New Vikunja ticket recommended.
2. **Verify #34532 closure mechanism + update charter §5**. The charter
   currently lists #34532 as "open, triaged"; live state shows closed.
   Documentation drift requires a charter update. Small ticket.
3. **Address andrey-golubev review feedback on npu_compiler PRs
   #265+#266**. Outside this workstream's scope. Significant effort
   (root-cause investigation). Separate workstream candidate, not just
   a Vikunja ticket.
4. **Fence-post fix in dispatch.xml §B1**: dispatch says "11 days since
   filed" but the recheck shows 12 days fence-post-corrected (May 1 → May
   12). Trivial doc fix when next edit of the workstream README / next
   dispatch is authored. Stage 6.7.5-style.
5. **PR #34651 last-activity delta**: dispatch §B2 said 2026-04-16; live
   state shows 2026-04-24. Eight-day delta. Likely a force-push or
   master sync. Document the correction in the workstream STATUS.md when
   Guide-#11 records the Phase 1 verdict.

### 7c. Phase 1 NON-recommendations (explicitly do not do these in Phase 1)

- Do **not** re-ping PR #34651's reviewers. Per dispatch §exclusions and
  charter §2.
- Do **not** open a #35641-fix PR pre-emptively. Phase 2 starts with
  build environment setup + plugin recon, not PR submission.
- Do **not** engage on any other open Intel issue in this workstream.
  Issue #35641 is the singular Phase 1 target.
- Do **not** post the engagement comment without LA review of the
  AI-Assistance block and the single @-mention selection.

---

## 8. Portfolio-shape summary

The LA's current OpenVINO upstream portfolio:

| Item | Type | State | Live status |
|---|---|---|---|
| openvino#35641 | issue | open | Engagement initiation pending (this Phase 1) |
| openvino#34651 | PR | open | Stalled; precedent for #35641 engagement |
| openvino#34617 | issue | open | Closure target of #34651; tracks #34651's state |
| openvino#34450 | issue | closed | Closure mechanism unverified; out of scope |
| openvino#34532 | issue | closed | Charter says "triaged"; live shows closed (drift) |
| npu_compiler#265 | PR | open | Reviewer feedback pending response |
| npu_compiler#266 | PR | open | Reviewer feedback pending response |

**Net Phase 1 posture**: one initiation, six state-tracked items.
The workstream's Phase 1 critical path is the #35641 engagement; the
other six are context for Guide-#11 and LA when deciding workstream
re-prioritization at Phase 2 dispatch authoring.
