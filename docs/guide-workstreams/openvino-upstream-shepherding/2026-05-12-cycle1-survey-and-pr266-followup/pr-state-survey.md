# PR state survey — cycle 1 (2026-05-12)

Live state captured via GitHub REST API on 2026-05-12 (post-engagement on issue #35641).
Per memory `feedback_github_comments_use_api_not_webfetch.md`, all checks use API
endpoints, not HTML page scraping.

## Summary

| PR | Repo | State | Last reviewer action | Last LA action | Days stalled | Recommended cycle-1 action |
|---|---|---|---|---|---|---|
| #34651 | openvino | open, no reviews, `mergeable_state: unstable` | none — zero reviews ever | 2026-04-25 (rebase) | 17 days since LA touch; \~60 days since open | Wait |
| #265 | npu_compiler | open, CHANGES_REQUESTED, `mergeable_state: unstable` | `andrey-golubev` CHANGES_REQUESTED 2026-04-17 (read-only perms) | 2026-04-17 (LA replied to review) | 25 days | Wait — same reviewer / same concern as #266 |
| #266 | npu_compiler | open, CHANGES_REQUESTED, `mergeable_state: unstable` | `andrey-golubev` CHANGES_REQUESTED 2026-04-17; `DariaMityagina` requested LIT test 2026-04-17 | 2026-04-17 (LA added LIT test + replied) | 25 days | Polite follow-up — re-surface IR-dumping question + flag Daria on the LIT test |

## PR #34651 — openvino — NPU unbounded-dynamic-shape guard

- **URL**: https://github.com/openvinotoolkit/openvino/pull/34651
- **Branch**: `blairducrayoppat:fix/npu-unbounded-dynamic-shape-guard` → `master`
- **Head SHA**: `7ec5e26f77fe1eeaa2ff180db2d2f468f88ca192`
- **Labels**: `ExternalPR`, `category: NPU`
- **Commits**: 2 · **Files changed**: 2 · **+133 / -0**
- **Closes**: issue #34617
- **Created**: 2026-03-12T07:10:32Z
- **Last updated**: 2026-04-25T21:57:32Z (force-push / rebase by LA)
- **mergeable_state**: unstable (CI workflows need an Intel staffer's approval to run for external contributors; nobody has clicked the approve-workflow button)

### Comments

1. `blairducrayoppat` 2026-04-16T21:47:15Z — *"Rebased against current master. This addresses #34617 (PSE-labeled, assigned to @YuChern-Intel / @Munesh-Intel). When convenient would someone from the NPU team approve the workflow run and review?"*

### Formal reviews

**None.** The reviews API endpoint returned an empty array.

### Status interpretation

This PR is in the same shape #35641 was in before we engaged: total
silence. No formal reviewer assignment, no comments, no workflow
approval, no CI status. The 2026-04-25 update was the LA rebasing.

### Cycle-1 recommendation: wait

Re-pinging a stalled PR with no engagement rarely accelerates review.
The more productive analog (proven on #35641 today) is to post on the
**underlying issue** with fresh data the maintainers can react to.
That option is open here too — issue #34617 is still open and would
welcome a fresh-state comment if the LA has anything new to add (e.g.,
the same problem still reproduces on OV 2026.1.0, etc.). But this is
a **future-cycle** decision, not a this-cycle action. Recommendation:
do nothing on #34651 this cycle; re-evaluate in 2-3 weeks.

## PR #265 — npu_compiler — ConvertFCToConv zero-dim guard

- **URL**: https://github.com/openvinotoolkit/npu_compiler/pull/265
- **Branch**: `fix/convert-fc-to-conv-zero-dim-guard` → `develop`
- **Head SHA**: `ebf56039e0d5cc16501fc3a536f7c6574c4aa2d3`
- **Commits**: 1 · **Files changed**: 3 · **+141 / -2**
- **Created**: 2026-03-04T06:13:08Z
- **Last updated**: 2026-04-17T17:00:56Z (LA's reply)
- **mergeable_state**: unstable

### Comments

1. `blairducrayoppat` 2026-04-16T21:48:29Z — *"Rebased against current develop. This is the primary fix for the SIGABRT crash reported in openvinotoolkit/openvino#34450 (PSE, assigned). The addDynamicallyLegalOp approach follows the existing pattern in AdjustNCEOpsWithI32InputsPass. LIT test included."*
2. `blairducrayoppat` 2026-04-17T17:00:56Z — Acknowledges andrey-golubev's review on #266 (the architectural concern), accepts the direction, calls the PR "defense-in-depth, not the long-term fix," explains that the zero-dim is introduced by an intermediate pass (not present at `GroupWisePatternRewriter`), and **asks andrey for guidance on IR dumping between passes** so the LA can identify the source pass.

### Formal reviews

1. `andrey-golubev` 2026-04-17T10:00:40Z — **CHANGES_REQUESTED** (read-only-permissions):

> Hi, thanks for you contribution! I believe the root cause here stems from the fact that an operation with zero-dim tensor exists at all. This should be prohibited by NPU compiler. (As in the other PR opened - https://github.com/openvinotoolkit/npu_compiler/pull/266). Similar rationale applies: if it's a problem originating in OpenVINO, I think we have to speak with OpenVINO maintainers to fix this. If it's a problem originating in compiler, it has to be fixed in the place where such a zero-dim tensor appears.

### Status interpretation

The reviewer agrees the symptom guard is OK but wants the root cause
fixed at the source. The LA accepted the direction and asked for help
identifying the source — specifically, how to dump IR between passes.
The reviewer has not responded for 25 days.

### Cycle-1 recommendation: do not follow up on #265 separately

Same reviewer / same architectural concern / same outstanding question
as #266. If we follow up on #266, the answer applies to both PRs.
Pinging two PRs in the same week for the same person is noisy.

## PR #266 — npu_compiler — UnrollFullyConnected zero-dim guard

- **URL**: https://github.com/openvinotoolkit/npu_compiler/pull/266
- **Branch**: `fix/unroll-fc-zero-dim-guard` → `develop`
- **Head SHA**: `c5f926628a0864b51cfad5750b634bd14554948f`
- **Commits**: 4 · **Files changed**: 3 · **+113 / -0**
- **Created**: 2026-03-04T06:17:56Z
- **Last updated**: 2026-04-17T16:57:31Z
- **mergeable_state**: unstable

### Comments

1. `blairducrayoppat` 2026-04-16T21:48:59Z — *"Rebased against current develop (merge commit removed — clean linear history). Companion defense-in-depth for #265. Minimal change (+54 lines)."*
2. `DariaMityagina` (CONTRIBUTOR) 2026-04-17T09:16:57Z — *"@blairducrayoppat hi! Could you please cover your changes with a LIT test?"*
3. `blairducrayoppat` 2026-04-17T16:49:18Z — Extended response detailing LIT test addition at `tests/lit/NPU/dialect/IE/passes/unroll_fully_connected_zero_dim_guard.mlir`, empirical verification of zero-batch FC unrolling behavior without the guard, root cause investigation findings, and the IR-dumping methodology request.

### Formal reviews

1. `andrey-golubev` 2026-04-17T09:58:08Z — **CHANGES_REQUESTED** (read-only-permissions):

> Hi, thanks for you contribution! I believe the root cause here stems from the fact that an operation with zero-dim tensor exists at all. This should be prohibited by NPU compiler. Does it come from OpenVINO directly? I'd say then we have to talk with OpenVINO to decide how this should be handled, because right now I would suggest to just reject such a model. Alternatively, if zero-dim tensor comes from another compiler pass, this is where it has to be fixed.

### Status interpretation

Two pending threads:
1. **andrey-golubev's architectural concern** — same as #265. LA asked
   for IR-dumping guidance; awaiting reply.
2. **DariaMityagina's LIT-test request** — LA added the LIT test
   inside their 2026-04-17T16:49 comment. Daria has not re-engaged
   to confirm the test is what she wanted.

### Cycle-1 recommendation: post a polite follow-up

Draft is at `pr-npu-compiler-266-follow-up-draft.md` in this cycle directory.
The draft re-surfaces both pending threads in one comment, light and
non-naggy. 25 days is a reasonable interval for one well-spaced
follow-up.

## "Read-only permissions" interpretation (LA-facing)

The GitHub UI tag "Requested changes with read-only permissions" on
both `andrey-golubev` reviews indicates:

- His association on `openvinotoolkit/npu_compiler` is `NONE` per the
  API (i.e., he has Read access only, not Write).
- His `CHANGES_REQUESTED` is **substantive feedback** the LA must
  address — and the LA has (responded technically, asked clarifying
  question).
- It is **not a hard merge-blocker** under branch-protection rules
  — only Write+ reviewers can technically gate a merge.
- An eventual Intel maintainer with Write access will be the actual
  merger. They will read andrey's review and most likely respect it.

What this means in practice: nothing about the LA's required action
changes. The action is what it would be for any CHANGES_REQUESTED
review — engage with the substance, resolve the conversation, wait
for the merger. The LA already did the engagement; this cycle's
recommendation is just to gently re-surface the open question.

## Other items watched but not shepherded this cycle

Per the `-int8-guard` workstream's `upstream-state-report.md`, the LA
has additional touched items (issues #34532, #34450, #34617, #33946,
#33776 and others). These are watched passively; no cycle-1 action.
Re-evaluate next cycle.
