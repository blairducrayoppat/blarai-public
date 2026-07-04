# Workstream STATUS — openvino-upstream-shepherding

Append-only chronological log. Never edit prior entries. One entry per
shepherding cycle or workstream-level decision.

---

## E1 — Workstream founded (2026-05-12)

- **Founder**: Guide-#11 (session "Intel Contribution May 12th")
- **LA**: Blair
- **Vikunja parent task**: project 3, task **#466**

### Founding context

The LA asked during the openvino-contribution-npu-int8-guard session
to expand scope to a separate, lighter shepherding layer covering all
of their open OpenVINO upstream items. Quoting the LA:
*"Create new workstream: 'OpenVINO-shepherding' where an agent (or
agents) helps me understand what is happening on the GitHub tickets,
do any related testing, create related solutions to problems, and post
at professional-level quality on GitHub."*

This workstream is the result. Charter sets the boundary:
shepherding-light (state monitoring + comment drafting + retests +
cadence management). Deep code authoring still spins out into its own
focused workstream (the `-int8-guard` template).

---

## E2 — Cycle 1: state survey of three PRs + #266 follow-up draft (2026-05-12)

Triggered by LA review of PR #34651, npu_compiler #265, npu_compiler #266
following completion of the issue #35641 engagement work earlier the
same day.

### Items surveyed (live via GitHub REST API)

- **openvino#34651** — stalled. No formal reviews. Last touch 2026-04-25 (LA rebase). `mergeable_state: unstable` (CI gating).
- **npu_compiler#265** — `CHANGES_REQUESTED` by `andrey-golubev` (read-only-permissions review) on 2026-04-17. LA responded 2026-04-17 asking for IR-dumping guidance. Stalled since.
- **npu_compiler#266** — same `CHANGES_REQUESTED` from `andrey-golubev` 2026-04-17, plus `DariaMityagina` (CONTRIBUTOR) requested a LIT test 2026-04-17. LA added the LIT test and asked for IR-dumping guidance on the same date. Stalled since.

Full survey written to `2026-05-12-cycle1-survey-and-pr266-followup/pr-state-survey.md`.

### "Requested changes with read-only permissions" — what it means (LA-facing)

LA asked what the read-only-permissions tag means and whether it
required action. Plain-language answer recorded:
- GitHub UI labels a `CHANGES_REQUESTED` review with "read-only
  permissions" when the reviewer has only Read access to the repo.
- The review is real feedback; substantively the LA must still
  address it.
- But it does NOT hard-block the merge under branch-protection
  rules — the eventual merger (someone with Write+) sees the review
  but is not forced to wait on its resolution.
- For LA's PRs #265 / #266, this means andrey-golubev's review is
  authoritative-feedback-to-resolve but not a merge gate; an Intel
  maintainer with Write access will be the actual merger.

### Cycle 1 outputs

- `2026-05-12-cycle1-survey-and-pr266-followup/pr-state-survey.md`
  — consolidated state of all three PRs.
- `2026-05-12-cycle1-survey-and-pr266-followup/pr-npu-compiler-266-follow-up-draft.md`
  — paste-ready follow-up for the LA to post on PR #266 (re-surfaces
  the IR-dumping question without nagging; light flag for Daria
  about the added LIT test).
- Vikunja per-PR "Shepherd:" tracking tickets opened for #34651,
  #265, #266.

### Cycle 1 recommendations (LA decisions pending)

1. **#266 follow-up** — post the drafted follow-up.
2. **#265 — leave alone for now.** Same reviewer / same architectural
   concern; #266 follow-up's IR-dumping answer applies to both.
3. **#34651 — don't ping yet.** Re-evaluate in \~2-3 weeks (i.e., by
   2026-06-01 to 2026-06-15). If still no engagement, consider
   posting on underlying issue #34617 with fresh data, similar to
   what we did for #35641.

### Open question for LA

Cadence preference: should monitoring be **scheduled** (e.g., a
ScheduleWakeup / CronCreate every 2-3 weeks to re-survey state) or
**LA-triggered** (LA pings when something feels stuck)? The LA's
preferred style determines whether this workstream gets a periodic
"check in" mechanism or stays purely reactive.

---

## E3 — Cycle 1 close-out: follow-up posted + cadence decided (2026-05-12)

### Cadence decision (LA)

**LA-triggered.** Quoting LA: *"The shepherding workstream is
LA-triggered."* The workstream stays reactive — no recurring
auto-check. Guide acts when LA pings.

Charter §4 updated to reflect this.

### Cycle 1 follow-up posted

- **PR**: npu_compiler#266
- **Comment URL**: https://github.com/openvinotoolkit/npu_compiler/pull/266#issuecomment-4433149755
- **Comment ID**: `4433149755`
- **Posted by**: blairducrayoppat
- **Posted at**: 2026-05-12T17:38:18Z
- **Verified via**: GitHub REST API direct comment lookup
- **Total comments on PR #266 after post**: 4

### LA edits applied to the v1 draft before posting

LA made tone adjustments before posting (captured in
`2026-05-12-cycle1-survey-and-pr266-followup/decisions.md` for future
drafting calibration). Two of those edits surfaced as observations
worth recording:

1. **`[SHA]` placeholder posted unmodified.** v1 draft had a placeholder
   `[SHA]` for the LA to substitute with the actual commit SHA `c5f9266`.
   The LA pasted the comment with the literal `[SHA]` still in. Daria
   will see "commit `[SHA]`". GitHub allows editing one's own comments;
   LA decides whether to fix. Future-draft default: Guide pre-fills the
   actual SHA so no placeholder substitution is needed.
2. **AI Assistance disclosure block removed before posting.** v1 draft
   had it; LA stripped it. Editorial choice. Inconsistent with the
   #35641 comment (which kept the disclosure). LA's call whether to add
   it back via edit. Future-draft default: include AI Assistance unless
   LA pre-states otherwise.

### Cycle 1 outcomes

- **#266**: follow-up posted. Now waiting on andrey-golubev (IR-dumping
  guidance) and DariaMityagina (LIT-test confirmation).
- **#265**: no action this cycle. Same reviewer / same concern as #266
  — andrey's eventual response covers both.
- **#34651**: no action this cycle. Re-evaluate \~2026-06-01 to 2026-06-15.
  If still silent, consider posting on underlying issue #34617 with
  fresh data.

### Vikunja state

- Parent #466: cycle-1 close-out comment added.
- #467 (Shepherd #34651): unchanged.
- #468 (Shepherd #265): unchanged.
- #469 (Shepherd #266): comment added with posted URL.

### Next cycle

LA-triggered. Workstream is quietly Active. No further Guide action
until LA pings — either with a state change (Intel reply, upstream
release, related issue filed) or a "let's check in" prompt.

---

## E4 — Cycle 1 correction: cited SHA was wrong (2026-05-12)

LA pushed back on the Guide's commit-SHA citation in the cycle-1
follow-up draft. The Guide had cited `c5f9266` (the PR head SHA) as
"the commit that added the LIT test." Verification via the
file-path-filtered commit history endpoint
(`/repos/blairducrayoppat/npu_compiler/commits?path=tests/lit/.../unroll_fully_connected_zero_dim_guard.mlir&sha=fix/unroll-fc-zero-dim-guard`)
revealed:

- **`9c7526f`** (full: `9c7526faacf2c593dcf63640cc94b46f0005afdd`),
  2026-04-17T16:44:22Z, message *"test: add LIT test for zero-dim guard
  in UnrollFullyConnected"* — **the actual test-introducing commit**.
- `c5f9266` (full: `c5f926628a0864b51cfad5750b634bd14554948f`),
  2026-04-17T16:47:15Z (3 minutes after `9c7526f`), message
  *"docs: update PR description — LIT test now included"* — head SHA
  but only updates the PR description doc, not the test file.

### Impact

The cycle-1 v1 draft had a `[SHA]` placeholder that the Guide had
inferred should be substituted with `c5f9266` (head SHA assumption).
The LA posted the comment with the placeholder unsubstituted, so
no wrong SHA reached the GitHub thread. Had the LA substituted the
placeholder using the Guide's (wrong) assumption, Daria would have
clicked the link and landed on a doc-only diff with no test in sight.

### Recommendation (revised)

If the LA chooses to edit the live PR #266 comment to substitute the
placeholder, use **`9c7526f`** (not `c5f9266`). Full SHA
`9c7526faacf2c593dcf63640cc94b46f0005afdd` is also acceptable for
unambiguous reference.

### Discipline change going forward

New memory note added: `feedback_verify_commit_sha_against_file_history.md`.
Required practice: before citing any commit SHA in any external-facing
artifact, verify via the file-path-filtered commit history endpoint.
No `[SHA]` placeholders in LA-handed drafts; Guide pre-fills the
verified SHA so the LA never sees a placeholder to substitute.

Quoting the LA: *"Never again make that assumption."*

---
