# OpenVINO Upstream Contribution — NPU INT8 Construct-Time Guard

## 1. Charter

Contribute a mature, professional-grade fix to OpenVINO upstream targeting
[issue #35641](https://github.com/openvinotoolkit/openvino/issues/35641), in
which `LLMPipeline(ir, "NPU")` silently accepts an INT8 weight-only
Intermediate Representation (IR) and then terminates the process with an
uncatchable Windows access violation (`0xC0000005`) on the first
`pipe.generate()` call. The required fix is a construct-time precision guard
that rejects unsupported weight formats with a clear, catchable Python
exception — mirroring the pattern proposed in PR
[#34651](https://github.com/openvinotoolkit/openvino/pull/34651) (authored
by the same contributor, currently in review limbo).

Terminology note: throughout this workstream, **openvino#35641** is the
**issue** being addressed; **openvino#34651** is the **PR** that serves as
the precedent template. Any future code contribution would itself be a PR
(either extending #34651 or as a separate companion PR), not the issue.

The workstream's success bar is **"Intel-grade contribution that builds trust"**
— not just a merged patch. *Mature not minimal*: engage maintainers first,
leverage the existing precedent PR, follow the AI Usage Policy disclosure,
accept Intel's preferred contribution shape, and treat slow-review as a
coordination problem, not a blocker.

## 2. Scope boundary

### In scope

- A construct-time guard fix addressing the INT8 weight-only failure mode
  on NPU described in issue #35641
- Engagement and coordination with Intel maintainers (diego-villalobos,
  Zulkifli-Intel, Munesh-Intel; cross-reference YuChern-Intel on the related
  PR #34651)
- AI Usage Policy compliance disclosure on any artifact submitted upstream
- A clean, well-described contribution (whether standalone PR or as an
  extension of PR #34651, per Intel's steer)
- Reproduction of the #35641 failure in a source-built OpenVINO before any
  PR is submitted
- BlarAI runtime uptake of the fixed OV build once shipped

### Out of scope (defer to follow-up workstreams)

- Audit of other silent-construct → uncatchable-crash failure modes on NPU
  (other weight formats, mismatched group sizes, unsupported architectures)
- Reviving PR #34651 itself — its stall is *observed* but not *driven* by this
  workstream. If the topic surfaces during engagement, surface to LA; do not
  unilaterally re-ping or restructure PR #34651.
- Any GPU-plugin work, ScatterUpdate (issue #34532) work, or other parallel
  upstream issues. State checks on those are allowed for engagement-context only.
- BlarAI-side runtime config changes (BlarAI's stack does not currently expose
  INT8-on-NPU; the fix is needed upstream regardless of BlarAI surface area).

## 3. Owners

- **Lead Architect**: Blair (`mr.blair.do@gmail.com` / GitHub `blairducrayoppat`)
- **Guide instance**: Guide-#11. Predecessor Guide-#10 closed Stage 6.7.5 on
  2026-05-08.
- **Vikunja parent task**: project 3 (`BlarAI Core Development`), task **#443**
- **Upstream issue (primary target)**: [openvino#35641](https://github.com/openvinotoolkit/openvino/issues/35641),
  filed 2026-05-01; assignees diego-villalobos, Zulkifli-Intel, Munesh-Intel
- **Precedent PR (same author, same plugin layer)**: [openvino#34651](https://github.com/openvinotoolkit/openvino/pull/34651)
- **Related closed issue (cited in #35641 body)**: [openvino#34450](https://github.com/openvinotoolkit/openvino/issues/34450)
- **Related issues**: [openvino#34617](https://github.com/openvinotoolkit/openvino/issues/34617)
  (closure target of PR #34651), [npu_compiler#265](https://github.com/openvinotoolkit/npu_compiler/pull/265)
  and [npu_compiler#266](https://github.com/openvinotoolkit/npu_compiler/pull/266)
  (prior author work)

## 4. Phase plan

Final phase shape is set after Phase 1's engagement response. Initial sketch:

| Phase | Slug | EA | Status | Description |
|---|---|---|---|---|
| 1 | `phase1-ea17-coordinate-with-intel` | EA-17 | Pending | Engagement: status-check PR #34651 / issues #34450 #34532 #34617 / npu_compiler #265+#266; read OV CONTRIBUTING + AI Usage Policy; draft #35641 engagement comment linking to PR #34651 as precedent and inviting Intel to direct the contribution shape; draft CLA + AI-Usage compliance brief for LA |
| 2 | TBD | TBD | Blocked on Phase 1 verdict | Build environment setup + NPUW LLM construct-path recon (locate guard insertion point in `src/plugins/intel_npu/`) |
| 3 | TBD | TBD | Blocked on Phase 2 | Source-build reproduction of #35641 against `master` to establish known-bad baseline |
| 4 | TBD | TBD | Blocked on Phase 3 | Implementation: construct-time guard + tests (shape per Intel's Phase 1 steer) |
| 5 | TBD | TBD | Blocked on Phase 4 | PR submission, CI shepherding, review iteration |
| 6 | TBD | TBD | Blocked on Phase 5 | Aftercare: BlarAI runtime uptake of fixed OV build, close-out STATUS entry |

EA-17 is the next global EA instance. Stage 6.7.5 ended with EA-16 (Phase 7
close-out). Per BlarAI memory note "EA numbering is global, not stage-scoped".

Ack namespace for Phase 1: `g11-ea17_n{K}`.

## 5. Linked tickets

- **Vikunja parent**: project 3 (`BlarAI Core Development`), task **#443**
- **Upstream issue (primary)**: openvino#35641
- **Upstream PR (precedent)**: openvino#34651
- **Upstream related issues**: openvino#34450 (closed; closure mechanism not visible — pending verification ticket), openvino#34617 (open, closure target of PR #34651), openvino#34532 (closed, last activity 2026-03-06 — corrected from initial "triaged" claim per EA-17 Phase 1 anomaly A-NEW4)
- **Upstream related PRs**: npu_compiler#265, npu_compiler#266

## 6. State

**Current state**: `Active` (initial, 2026-05-12)

### Closure criteria

Any one of these is sufficient to transition to `Complete`:

1. Intel merges a fix for issue #35641 (ours, an extension of PR #34651, or
   an internal Intel patch) **AND** the BlarAI runtime team confirms the
   failure no longer reproduces with a released OV build that contains the fix.
2. Intel formally closes issue #35641 with documented disposition (e.g., "INT8
   weight-only on NPU LLM unsupported by design — error surfaced via
   `CONTRIBUTING.md` or model card"). In that case, BlarAI documents the
   supported-format constraint in its runtime docs and the workstream closes.
3. LA decides to abandon the contribution. Transition to `Deferred` with a
   documented resume condition rather than `Complete`.

### Deferral conditions

If by 2026-07-01 PR #34651 remains stalled **and** issue #35641 has received
no substantive Intel response, escalation paths (Intel DevHub Discord, GitHub
Discussions per OpenVINO CONTRIBUTING.md guidance) are available — but
escalation is a Phase-1+ outcome decision, not a workstream commitment.
