# CLA + AI Usage Policy compliance brief

**Purpose**: give the LA everything needed to (a) confidently post the
engagement comment on openvino issue #35641 without a CLA-bot block, and
(b) compose the eventual #35641-fix PR description with a compliant AI
Assistance disclosure block.

**Scope**: terminology — openvino#35641 is the **issue** being engaged
on; PR #34651 is the **precedent PR**. Throughout this brief, "the
eventual PR" refers to any future code PR fixing issue #35641, whether
that PR extends #34651 or is a separate companion.

---

## 1. CLA status for `blairducrayoppat`

**Finding**: **Active — no LA action needed before posting the engagement
comment**. The comment is a non-code GitHub comment; CLAs are typically
checked at PR creation, not at comment creation. Even on the eventual
#35641-fix PR, the inference below indicates the CLA is already on file.

**Method of verification** (preflight 0i):

1. Inspected PR #34651's check timeline via WebFetch of
   `https://github.com/openvinotoolkit/openvino/pull/34651/checks` and
   the PR conversation page. No CLA bot status (EasyCLA / Linux
   Foundation CLA / similar) is visible.
2. Inspected the PR's labels and conversation timeline for any "CLA
   missing", "EasyCLA pending", "needs-cla" or equivalent block markers.
   None found.
3. Inferred: PR #34651 has been open since 2026-03-12 (~62 days at
   dispatch time) labelled `ExternalPR`. If a CLA were unsigned, OpenVINO
   tooling would have surfaced it long before now; absence of any CLA
   surface on a long-stale ExternalPR is strong (though not absolute)
   evidence the CLA either is already signed or that OpenVINO does not
   gate on a blocking CLA bot for this repository.

**Uncertainty**:

- OpenVINO's CONTRIBUTING.md and CONTRIBUTING_PR.md do **not** mention a
  CLA requirement in their visible text (preflight 0h). This is unusual
  for a Linux-Foundation-adjacent project; it may be that OpenVINO
  inherits CLA mechanics via a parent organization configuration not
  surfaced in the contributor docs.
- The inference "no CLA bot visible on #34651 → CLA is fine" is robust
  but not airtight. A maintainer enabling CLA checks at PR-#35641-fix
  open time could surface a sign-once flow at that point.

**LA fallback if a CLA bot does surface**:

1. The CLA prompt will typically appear as an inline check on the PR
   page with a link of the form
   `https://easycla.lfx.linuxfoundation.org/#/cla/...` or
   `https://cla.intel.com/...`.
2. Click through and sign (sign-once persists for the GitHub account).
3. The CLA bot re-runs automatically and the check turns green within
   minutes.
4. No re-submission of the PR is needed; CLA signing is decoupled from
   commits.

**Recommendation**: LA may post the engagement comment without a
pre-flight CLA confirmation step. The eventual PR is the only point at
which a CLA gate plausibly triggers, and the per-step recovery is fast.

---

## 2. AI Usage Policy — verbatim relevant excerpts

**Live policy URL**:
`https://github.com/openvinotoolkit/openvino/blob/master/AI_USAGE_POLICY.md`

**Last modified**: 2026-02-20 (commit `c4f4325`), introduced via
PR #34172 ("[DOCS] Add AI usage policy and PR disclosure guidance") by
maintainer `mlukasze`. **This is the same policy text that was in effect
when PR #34651 was opened on 2026-03-12** — there is no policy delta
between the precedent PR's submission and any future #35641-fix PR.

### 2a. Suggested disclosure format (verbatim)

```
AI assistance used: <no | yes>
If yes: <how AI was used>
Human validation performed: <build/tests/manual checks>
```

### 2b. Core contributor responsibilities (verbatim list)

Contributors using AI must:

1. **Understand submissions completely** and explain design/implementation
   decisions.
2. **Self-verify correctness** through building, testing, and checking
   edge cases.
3. **Accept full accountability** for every submitted line.
4. **Disclose significant AI assistance** in PR descriptions.

### 2c. Prohibited practices

- Submitting code you cannot explain or maintain.
- Large, low-context AI changes without thorough human validation.
- "Fabricated citations, benchmarks, bug reports, or security claims."
- Auto-generated issues without reproducible first-hand observations.

### 2d. Enforcement basis

"Not based on AI detection" — enforced via "observed contribution quality".

### 2e. PR-template AI section (verbatim from `.github/pull_request_template.md`)

```
### AI Assistance:

* _AI assistance used: no / yes_
* _If yes, summarize how AI was used and what human validation was performed (build/tests/manual checks)._
```

### 2f. Commit-message conventions

The AI Usage Policy itself does **not** mandate any commit-message
convention.

---

## 3. Disclosure template for the eventual #35641-fix PR

The LA may paste the following block verbatim into the eventual PR
description's `### AI Assistance:` section. This mirrors the structure
in `BlarAI/docs/PR_34617_DESCRIPTION_PASTE.md` §AI Assistance, adjusted
for #35641 specifics.

### Template (paste-ready)

```
### AI Assistance:

* AI assistance used: yes.
* AI tools used: GitHub Copilot (source-code analysis to locate the
  insertion point in plugin.cpp, and to confirm the construct-time
  detection path for INT8 weight-only weights in IR metadata); Claude
  (for engagement-comment authoring on issue #35641, for this PR
  description, and for the commit message).
* Human validation: The fix logic, insertion point in
  src/plugins/intel_npu/src/plugin/src/plugin.cpp, and detection
  mechanism (introspection of IR weight-format metadata, not heuristic
  matching) were determined through manual analysis. The reproduction
  evidence in issue #35641 (Windows STATUS_ACCESS_VIOLATION 0xC0000005,
  exit code -1073741819, openvino.dll v2026.0.0.20965 faulting offset
  0x77d86, EXECUTION_DEVICES confirming NPU placement) was generated and
  recorded locally on Intel Core Ultra 7 258V (Lunar Lake) with NPU 4000
  by the contributor. The fix is tested against the same hardware and
  validated to convert the silent native crash into a catchable Python
  exception.
```

**Notes on the template**:

- The exact tool list ("GitHub Copilot ... Claude ...") matches honest
  attribution: Copilot for source code analysis; Claude (via the BlarAI
  Guide / EA workflow) for narrative authoring. This is wider attribution
  than PR #34651's disclosure (Copilot only) — the Guide/EA workflow is
  new since March 2026.
- The hardware-validation paragraph is required by AI Usage Policy 2.b.2
  ("Self-verify correctness ... building, testing, and checking edge
  cases"). The specifics named (NPU 4000, openvino.dll faulting offset)
  satisfy the policy's prohibition on "fabricated benchmarks / bug
  reports".
- The template assumes the eventual PR ships with at least one test
  case (analogous to PR #34651's optional unit test in
  `src/plugins/intel_npu/tests/unit/`). If Intel directs option (a)
  "extend PR #34651" and the existing PR has no test yet, the unit test
  approach in `PR_PACKAGE_ISSUE_34617.md` §6 is the template.

---

## 4. Compliance notes — any deltas since PR #34651 was opened?

**Finding**: **No material deltas**. The AI Usage Policy text in effect
on 2026-05-12 is the same text that was in effect on 2026-03-12 when
PR #34651 was opened (commit `c4f4325`, 2026-02-20, never amended).

**Implication**: the precedent disclosure pattern in PR #34651 can be
re-used directly for the eventual #35641-fix PR with only #35641-specific
content swapped in (failure mode, hardware confirmations, scope of AI
tooling assist).

**One adjustment**: PR #34651 disclosed Copilot-only because that was
the only AI tool the LA was using in March 2026. The #35641 engagement
adds Claude (via the BlarAI Guide / EA workflow). The disclosure in §3
above reflects that adjustment honestly.

---

## 5. DCO / sign-off finding

**Finding**: **No DCO sign-off required**. Neither
`CONTRIBUTING.md` nor `CONTRIBUTING_PR.md` nor the PR template references
a Developer Certificate of Origin or a `git commit -s` requirement.

**Verification method**:

- Read `CONTRIBUTING.md` (preflight 0h): no DCO mention.
- Read `CONTRIBUTING_PR.md` (preflight 0h): no DCO mention.
- Read `.github/pull_request_template.md` (preflight 0h): no DCO field.
- Cross-checked PR #34651's commit history: commits have no `Signed-off-by:`
  trailer, and the PR has not been blocked on that basis.

**Implication**: the eventual #35641-fix PR's commits do NOT need `-s`.
If Intel maintainers later request DCO, it can be added retroactively
via `git rebase --signoff` and force-push — that's a fast recovery, no
re-opening required.

---

## 6. PR-quality requirements summary

From `CONTRIBUTING_PR.md` (preflight 0h, quoted verbatim):

- "Link your Pull Request to an issue if it addresses one." → The
  eventual #35641-fix PR description's `### Tickets:` section should
  contain `Closes #35641` (and any related-issue references).
- "Give your branches, commits, and Pull Requests meaningful names and
  descriptions." → Branch prefix like `fix/npu-int8-weight-only-guard`
  (mirroring `fix/npu-unbounded-dynamic-shape-guard` from PR #34651).
- "If your changes cover a particular component, you can indicate it in
  the PR name as a prefix, for example: `[DOCS] PR name`." → PR title
  prefix `[NPU]` per PR #34651's precedent.
- "Test your changes locally."
- "Run tests locally to identify and fix potential issues."
- "Ensure your branch is up to date with the latest state of the branch
  you want to contribute to."
- "Complete the AI section in the PR template for every PR and follow
  the AI Usage Policy."

---

## 7. LA-facing summary

| Question | Answer |
|---|---|
| Can LA post the engagement comment now? | Yes. No CLA gate on GitHub comments. |
| Is the CLA signed for `blairducrayoppat`? | Inferred yes (PR #34651 not CLA-blocked). LA may verify by clicking through any CLA prompt that surfaces at #35641-fix-PR-open time. |
| Did the AI Usage Policy change since PR #34651? | No. Same text, commit `c4f4325`, 2026-02-20. |
| Does the eventual PR need DCO `-s`? | No. |
| What disclosure block goes on the engagement comment? | See `engagement-comment-draft.md` — short two-sentence form, honest dual-tool attribution. |
| What disclosure block goes on the eventual #35641-fix PR? | See §3 above. |
| Any new compliance work since March? | No. The Phase 1 compliance posture is identical to PR #34651's. |
