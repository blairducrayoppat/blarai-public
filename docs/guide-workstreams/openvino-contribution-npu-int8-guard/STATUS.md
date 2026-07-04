# Workstream STATUS — openvino-contribution-npu-int8-guard

Append-only chronological log. Never edit prior entries. One entry per
phase-affecting outcome or workstream-level decision.

---

## E1 — Workstream founded (2026-05-12)

- **Founder**: Guide-#11 (session "Intel Contribution May 12th")
- **LA**: Blair
- **Vikunja parent**: project 3, task #443
- **Primary target**: openvino#35641 (issue, filed by LA 2026-05-01)

### Scope decision (LA)

Single-issue scope: just the construct-time guard addressing issue #35641.
Audit of other silent-construct → uncatchable-crash failure modes is deferred
to a hypothetical follow-up workstream, contingent on Phase 1 Intel reception.

### Posture decision (LA)

Engagement-first. No speculative PR. The success bar is "Intel-grade
contribution that builds trust", not just a merged patch. Quoting LA:
*"We are not looking to jump ahead with speculative PRs. I want to avoid
poor receptions. We want to add value for the Intel team and build trust."*

### Critical context discovered during workstream founding

1. **PR openvino#34651 (same author, same plugin layer) is the direct
   precedent** for the kind of fix issue #35641 needs — a ~25-line
   construct-time guard in `Plugin::compile_model()` that detects an
   unsupported config and throws an actionable catchable exception, using
   only existing public OpenVINO C++ APIs. As of 2026-05-12, PR #34651 is
   stalled: open since 2026-03-12, author rebase + review request on
   2026-04-16, no Intel reviewers assigned, no CI status visible, no review
   comments, no merge activity.

2. **Strategic implication**: submitting a second standalone guard PR (one
   fixing issue #35641) while PR #34651 stalls would scatter Intel's review
   attention across two PRs in the same NPU-plugin guard space. The Phase 1
   engagement comment on issue #35641 must therefore *link to* PR #34651
   and let Intel direct the contribution shape (extend the open PR, open a
   separate companion PR following the same pattern, or wait for Intel-internal
   work). This focuses attention rather than diluting it.

3. **Author has substantial OpenVINO upstream history** (per
   `BlarAI/docs/OPENVINO_CONTRIBUTION_PLAN_MARCH_2026.md` and related
   artifacts): issues #34450, #34532, #34617, #35641 filed; PRs
   openvino#34651 and npu_compiler#265/#266 authored; #34532 triaged with
   new Xe2 (Lunar Lake Arc 140V) findings. Phase 1 dispatch is therefore
   sized assuming established engagement style — not a first-contact intro.

4. **Engagement style precedent** (per
   `BlarAI/docs/ISSUE_34450_COMMENT_EDIT.md`): polite, suggests-not-demands,
   addresses engineers by @-mention, references related PRs, offers to
   adjust approach to the team's preferred pattern. This is the style
   template for the issue #35641 engagement comment.

5. **AI Usage Policy disclosure precedent** (per
   `BlarAI/docs/PR_34617_DESCRIPTION_PASTE.md` §"AI Assistance"): the prior
   PR #34651 disclosed `AI assistance used: yes — AI (GitHub Copilot) was
   used for: source code analysis, generating the guard clause
   implementation, drafting the PR description and commit message. Human
   validation: All code was reviewed and validated by the contributor.
   Build/test validation performed locally on Intel Core Ultra 7 258V with
   NPU 4000.` Phase 1 dispatch references this as the disclosure template;
   EA-17 must verify the policy text is unchanged before reuse.

### Terminology contract (per LA correction 2026-05-12)

- **openvino#35641** is an **issue**.
- **openvino#34651** is a **PR**.
- **openvino#34450** is an **issue** (closed).
- **openvino#34617** is an **issue** (closure target of PR #34651).
- **openvino#34532** is an **issue**.
- **npu_compiler#265, npu_compiler#266** are **PRs**.

All workstream artifacts, comment drafts, and commit messages MUST use the
correct noun. The dispatch encodes this as constraint `C-ISSUE-VS-PR` and
ack `g11-ea17_n7`.

### Artifacts created at founding

- `BlarAI/docs/guide-workstreams/README.md` (registry — new file)
- `BlarAI/docs/guide-workstreams/openvino-contribution-npu-int8-guard/README.md` (charter)
- `BlarAI/docs/guide-workstreams/openvino-contribution-npu-int8-guard/STATUS.md` (this file)
- `BlarAI/docs/guide-workstreams/openvino-contribution-npu-int8-guard/phase1-ea17-coordinate-with-intel/dispatch.xml` (Phase 1 dispatch)

### Next gate

Guide-#11 commits the founding artifacts on `main` (single trivial commit per
fleet-hygiene §4 "Single trivial file edit + immediate commit" — no pause
required). EA-17 is then spawned with the dispatch as its only context.
EA-17 executes per the dispatch; Guide-#11 cross-verifies the close report
and writes `verdict.md`.

---

## E2 — Phase 1 complete: PASS_WITH_NOTES (2026-05-12)

- **EA**: EA-17
- **Guide verdict**: PASS_WITH_NOTES (concurs with EA self-verdict)
- **Commits**:
  - Pause: `c58261a` (devplatform/main) — `state.pause_fleet(...)`
  - Content: `7702dba` (BlarAI/feature/p-openvino-35641-phase1-engagement)
  - Resume: `4bc274e` (devplatform/main) — `state.resume_fleet(...)`
- **Deliverables on disk**:
  - `phase1-ea17-coordinate-with-intel/engagement-comment-draft.md` (243 words, paste-ready for issue #35641)
  - `phase1-ea17-coordinate-with-intel/cla-and-ai-policy-brief.md`
  - `phase1-ea17-coordinate-with-intel/upstream-state-report.md`
  - `phase1-ea17-coordinate-with-intel/close-report.md` (EA self-report)
  - `phase1-ea17-coordinate-with-intel/verdict.md` (Guide-#11 cross-verification)

### Anomalies surfaced + dispositions

| ID | Description | Disposition |
|---|---|---|
| A-NEW1 | `devplatform/docs/governance/fleet-hygiene.md` §R7 example invocation cites `C:/Users/mrbla/BlarAI/tools/autonomy_budget/state.json` — actual canonical path is `C:/Users/mrbla/devplatform/tools/autonomy_budget/state.json`. EA-17's dispatch inherited the wrong path. | **Bound to new Vikunja ticket in DevPlatform-Meta (project 10)** for the fleet-hygiene doc fix. |
| A-NEW2 | Pre-existing uncommitted drift on devplatform working tree (`.mcp.json`, three wake-task xmls, two flag files, state.json timestamp). Not EA-17 work. | Informational only. No ticket — observed across multiple sessions per fleet-hygiene §1 drift catalogue. |
| A-NEW3 | PR #34651 actual last activity was 2026-04-24 (force-push/merge), 8 days later than the 2026-04-16 the Phase 1 dispatch §B2 claimed. | Informational — dispatch was authored from stale WebFetch summary. The engagement comment does not cite the date, so no LA-facing impact. |
| A-NEW4 | Charter §5 listed issue #34532 as "open, triaged" — live state is closed (last activity 2026-03-06). | **Fixed inline** in this E2 turn via charter edit. |

### Hardening followups bound to Vikunja

Per ack `g11-ea17_n5` (Hardening followups are NON-OPTIONAL):

1. Vikunja ticket in DevPlatform-Meta (project 10) — fleet-hygiene.md §R7 path fix.
2. Vikunja ticket in BlarAI Infrastructure (project 4) — verify issue #34450 closure mechanism (closure date + mechanism not surfaced in WebFetch extraction; needed for full historical record).

### Strategic finding from Phase 1

**Reviewer engagement is reviewer-pool-specific, not author-blocked.** npu_compiler PRs #265 + #266 (same author, blairducrayoppat) received actual reviewer engagement from `andrey-golubev` on 2026-04-17. PR #34651's stall is a property of the NPU plugin reviewer pool (YuChern-Intel / Munesh-Intel / Zulkifli-Intel) not having triaged it, not a property of the author. This strengthens the engagement posture: the #35641 comment may catalyze review on PR #34651 too if Intel chooses option (a), but should not depend on it.

### Phase 2 readiness

- **Blocked on**: substantive Intel response to the engagement comment on issue #35641 (or the workstream's 2026-07-01 deferral window passing).
- **Conditional shape**: Phase 2 work depends on which contribution shape Intel chooses (extend PR #34651 / separate companion PR / defer / fourth option).
- **Universal preflight to surface in Phase 2 dispatch**: source-build toolchain (Visual Studio 2022, CMake, Python, OpenCL + Level Zero) and disk-space + wall-clock requirements for initial OpenVINO submodule init + cmake configure.

### Next gate

LA reviews the engagement comment at
`phase1-ea17-coordinate-with-intel/engagement-comment-draft.md` and posts to
[issue #35641](https://github.com/openvinotoolkit/openvino/issues/35641) via
GitHub webUI. After posting, LA appends the comment URL here (or asks Guide
to). Workstream then waits for Intel response.

---

## E3 — Phase 1 AMENDMENT: missed comments discovery + engagement-comment v2 (2026-05-12)

**Discovery**: During final-summary review, the LA flagged that the v1
engagement comment did not address the actual conversation on
[issue #35641](https://github.com/openvinotoolkit/openvino/issues/35641).
Re-verification via the GitHub API
(`https://api.github.com/repos/openvinotoolkit/openvino/issues/35641/comments`)
returned **three comments** that all WebFetch HTML scrapes during Phase 1
had missed:

1. `dmfallak` (NONE, 2026-05-04) — related-but-distinct Meteor Lake
   compile failure (`StopLocationVerifierPass`); filing separately, cross-linking only.
2. `Zulkifli-Intel` (2026-05-06) — *"the NPU is approximately 15x slower
   than the GPU with the INT8 model precision. I'm referring this case to
   the dev team for further investigation."*
3. `diego-villalobos` (2026-05-06) — **could not reproduce the crash on
   OpenVINO 2026.1.0** (Linux + Windows); test output shows
   `CONSTRUCT_OK 6.13s` and `GENERATE_OK 16 tokens`. Asks whether the
   user's `2026.0.0` signature means this is a version-specific crash
   already resolved. Also confirms INT8 weight-only is **outside the
   officially supported NPU LLM matrix** per the docs.

### Root cause of the miss

WebFetch's HTML-summarization model for github.com pages systematically
fails to surface comments. Both Guide-#11's initial recon (2026-05-12 ~14:00Z)
and EA-17's preflight 0e re-verification (2026-05-12 ~15:23Z) used
the HTML page and returned "no comments visible" — false for all three.
The GitHub REST API endpoint returns the actual comments as structured
JSON. Codified in the new memory note
`feedback_github_comments_use_api_not_webfetch.md`.

### Corrections applied in E3

1. **Re-drafted engagement comment as v2** at
   `phase1-ea17-coordinate-with-intel/engagement-comment-draft.md`
   (overwrites v1; v1 preserved in git history at commit `7702dba`).
   The v2 comment:
   - Addresses all three commenters directly.
   - Acknowledges Diego's 2026.1.0 no-repro finding and **commits to
     retest** against 2026.1.0 on Lunar Lake (Core Ultra 7 258V /
     NPU 4000 / driver 4724).
   - Reframes the construct-time guard ask as the **separable durable
     defect** (silent acceptance of unsupported configuration → undefined
     behavior, independent of the crash status) — leaning on Diego's
     own docs reference.
   - Acknowledges dmfallak's cross-link without pulling that case in.
   - Keeps the three-options ask + fourth-option invitation.
   - Word count 248 (within 150–250 band).
2. **Memory note added**: `feedback_github_comments_use_api_not_webfetch.md`
   — use the GitHub REST API for any comment verification; HTML scraping
   misses comments.
3. **Followup hardening item** (pending Vikunja ticket creation in this
   E3 turn): update the Phase 1 dispatch's preflight 0d/0e/0f/0g to cite
   the GitHub REST API endpoint, not the HTML page, for any future
   workstream dispatches.

### Phase 1 status revision

Phase 1's deliverable status changes from **"engagement comment ready,
LA posts at convenience"** to **"engagement comment ready for retest +
post"**. The retest on OV 2026.1.0 is now an implicit Phase 1.5 step
between drafting and posting — without it, the comment's commitment to
"I'll retest" is unbacked.

### LA's revised next action

1. Review the v2 engagement comment at
   `phase1-ea17-coordinate-with-intel/engagement-comment-draft.md`.
2. Either:
   - **(a)** Have Guide-#11 (or an EA) execute the 2026.1.0 retest first,
     then update the v2 comment with the retest result and post.
   - **(b)** Post v2 as-is with the "I'll retest and report back"
     promise, and follow up with a second comment after retest.
   Recommend (a) — Diego's data is the most material part of the thread
   and our reply lands stronger with our own retest result. Option (b)
   is acceptable if speed matters more than data quality.
3. After posting, append the comment URL here.

---

## E4 — Phase 1.5: OV 2026.1.0 retest result; engagement comment v3 (2026-05-12)

LA selected option (a) from E3: retest first, then post with data. The
retest was executed by a foreground sub-agent (Retest-OV-2026.1.0) in an
isolated venv outside the BlarAI repo.

### Headline result

**Crash still reproduces on OV 2026.1.0 on Lunar Lake. 3/3 NPU runs. Deterministic. `0xC0000005`.**

Diego-villalobos's no-repro claim is **REFUTED on this hardware**.
Hypothesis: diego likely tested on a non-Lunar-Lake NPU SKU (different
silicon revision or BKC driver release); the access-violation site may be
specific to Lunar Lake NPU silicon + driver `32.0.100.4724` combination.

### Retest environment

- Host: Windows 11 Pro / Intel Core Ultra 7 258V (Lunar Lake)
- NPU: Intel AI Boost, driver `32.0.100.4724` (unchanged from original)
- GPU: Intel Arc 140V, driver `32.0.101.8724` (newer than original `6987`; not material to NPU crash)
- Isolated venv: `C:\Users\mrbla\.venv-ov2026.1` (outside BlarAI repo; BlarAI runtime venv untouched)
- Versions: openvino `2026.1.0-21367`, openvino_genai `2026.1.0.0-2957`, optimum `2.1.0`, optimum-intel `1.27.0`, transformers `4.57.6`, nncf `3.1.0`, torch `2.11.0`, Python 3.11.9

### Retest data (verbatim from `retest-2026.1-report.md`)

```
NPU run 1: construct=17.51s, generate=CRASH exit=-1073741819 (0xC0000005)
NPU run 2: construct=17.78s, generate=CRASH exit=-1073741819
NPU run 3: construct=18.29s, generate=CRASH exit=-1073741819
GPU control: construct=5.65s, generate=0.27s, exit=0, coherent output
```

### Bug definition refinement

On 2026.0.0, the original report framed this as a "construct + generate
crash". The 2026.1.0 retest shows `LLMPipeline(ir, "NPU")` now **returns
successfully in ~17-18s** — the access violation now fires inside
`pipe.generate(...)` ~3-4s into generation. So:

- 2026.0.0: silent construct **then** crash on generate (per original report)
- 2026.1.0: silent construct succeeds in ~18s, **then** crash on generate

Either way, the **separable defect** (silent acceptance of an unsupported
INT8-weight-only NPU LLM configuration that subsequently exhibits
undefined behavior) is unaffected by which version exhibits the crash.
The construct-time guard ask is **strengthened** by the refinement: the
NPU plugin compiles the graph for ~18s without complaint and only fails
once it tries to execute. A capability check at compile time has even
more value than at runtime.

### Engagement comment v3

Rewritten with the retest data:
`phase1-ea17-coordinate-with-intel/engagement-comment-draft.md` (v3).
v2 is preserved in git history at commit `7295427`. v3 leads with the
data block, includes a tactful hypothesis for the diego divergence, and
keeps the three-options ask.

### Artifacts added in E4

- `phase1-ea17-coordinate-with-intel/repro_int8_npu_2026.1.py` — minimal
  reproducer mirroring the original issue's test harness
- `phase1-ea17-coordinate-with-intel/retest-2026.1-report.md` — full
  retest report (environment, fingerprints, runs, conclusion,
  implications)

### File-disappearance anomaly (A-NEW5)

Both retest artifacts disappeared from the phase1 directory between the
retest agent writing them and the parent Guide attempting to commit
them. Backups at `C:\Users\mrbla\openvino-test-exports\` (outside the
repo) preserved the repro script; the retest report was recovered from
in-context Read history. The retest agent flagged a similar mid-retest
disappearance for the repro script. Root cause: very likely the SDO
`wake_launcher` post-session auto-stash mechanism (recent stashes
`stash@{0}` and `stash@{1}` are SDO wakes at 2026-05-12T09:05 and 09:09)
— wake_launcher's view of `fleet_paused` may not include the
devplatform-side pause Guide-#11 + EA-17 set (a downstream effect of
the same path-defect that #453 tracks). Hardening followup recommended:
either fix wake_launcher to honor the canonical devplatform state.json,
or document the wake-vs-Guide pause-coordination contract explicitly.

### Phase 1 status

**Comment ready for post.** No further retest blocks the post; the data
is concrete and load-bearing. Workstream waiting on Intel response after
LA posts.

### LA's next action

1. Review v3 engagement comment.
2. Optionally compress (it is 291 words; see v3's authoring note 8 for trim suggestions).
3. Re-verify live state via GitHub API one more time before posting.
4. Post via GitHub webUI.
5. Append the comment URL here.

### POSTED 2026-05-12 (v5)

The final draft posted to issue #35641 was **v5** (mature-not-minimal pass + humility-pass for tone), not v3. Evolution: v3 (commit `d2b535c`, 291 words) → v4 (`835f0db`, 490 words, mature-not-minimal pass) → v5 (`58db837`, 510 words, tone pass for humility).

- **Posted URL**: https://github.com/openvinotoolkit/openvino/issues/35641#issuecomment-4432950986
- **Comment ID**: 4432950986
- **Posted by**: blairducrayoppat (LA)
- **Posted at**: 2026-05-12T17:09:56Z
- **Verified via**: GitHub REST API direct comment lookup (`GET /repos/openvinotoolkit/openvino/issues/comments/4432950986`) — body byte-for-byte matches `engagement-comment-PASTE.md`; AI Assistance block intact; no truncation.
- **Issue comment count after post**: 4 (dmfallak 2026-05-04, Zulkifli-Intel 2026-05-06, diego-villalobos 2026-05-06, blairducrayoppat 2026-05-12).
- **No new Intel comments arrived between v5 drafting and posting** — framing is current.

### Phase 1 close

Phase 1 (engagement) is **closed-out**. Workstream stays `Active`. Phase 2 work (build environment + codebase recon → reproduction in source build → fix authoring) is blocked on substantive Intel response (likely from Zulkifli-Intel, diego-villalobos, or another NPU-plugin team member). Watch for:

- An Intel engineer answering the silicon-family question (Lunar Lake vs. their test platforms).
- A directive on contribution shape (extend PR #34651 / separate companion PR / wait for internal fix / different approach).
- An Intel-internal fix landing in master or in 2026.2.0 that obsoletes the contribution.

If no substantive Intel response by **2026-07-01**, the charter's deferral condition triggers and we consider escalation paths (Intel DevHub Discord, GitHub Discussions).

---
