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

## E5 — Cycle 2: PR #4139 (openvino.genai) hardware review + comment posted (2026-07-22/23)

Triggered by LA: maintainer `apaniukov` (Intel) left an architectural review comment on
openvino.genai PR #4139 (2026-07-22T10:54Z); the author `PlanteAmigor` (community member)
implemented it overnight (commit `8cf5e4502f330e423794aca8a1f7e299eed7c061`) and formally
re-requested review from apaniukov AND `blairducrayoppat` (2026-07-23T01:38Z).

### Standing correction (supersedes the 2026-07-22 session brief on this point)

The session brief claimed PlanteAmigor and blairducrayoppat are both the LA. Live evidence
(gh auth, git identity, commit authorship `amigor@users.noreply.modelscope.cn`, thread
dialogue, different test hardware) shows they are different people: the LA is a third-party
contributor / test bench / requested reviewer on someone else's PR. Also noted: engaging on
a PR the LA didn't author is outside the charter §2 as written; LA proceeded knowingly
(invited by the author, now a formally requested reviewer). Charter update is LA's call.

### Work done (all in `2026-07-22-cycle2-pr4139-review/`)

1. **Cheap pre-build check** (tokenizer-only): PR auto-detect succeeds on Qwen3.6-35B
   (`<think>`=248068 single token); default template puts 248068 at idx 18/20, last token
   `\n`=198 — falsified Guide's no-op prediction; confirmed author's 07-17 root cause at
   token level. → `cheap-check-prompt-tokenization.md`
2. **Two from-source builds** (venv-build, incremental): head `8cf5e450` and parent
   `5166cd3e` (only 2 files differ). Exact-token-ID streamer probe
   (`probe_pr4139_35b_v2.py`, repo root) on Arc 140V, Qwen3.6-35B-A3B-int4-ov official IR,
   VLMPipeline/GPU/greedy.
3. **Headline findings** (full record: `measurement-record-8cf5e450-vs-5166cd3e.md`):
   - `enable_thinking=False` works ID-less (auto-detect ≡ explicit IDs, byte-identical).
   - `reasoning_budget_tokens>0` silently no-ops at head on VLM non-chat; fired at exactly
     N=32 on parent. Root cause (code-verified): `visual_language/pipeline.cpp:802-806`
     passes pad-placeholder prompt_ids (pad=248044) to `LogitProcessor` (`sampler.cpp:1701`)
     → scan always IDLE on this path.
   - Parent's unconditional-COUNTING corrupted closed-block answers (spurious `</think>` at
     idx 32 mid-answer); head clean — empirical before/after validating apaniukov's
     suggestion, with the caveat head-D is right-for-the-wrong-reason on this path.
   - Coherence: mid-stream cap inserts the tag but model keeps reasoning after it.
4. **Comment drafted** (3 revision rounds with LA; calibration: facts plain, interpretation
   hedged, scope question routed to apaniukov, warm to community author, conditional
   prototyping offer) and **posted by LA**:
   - **URL**: https://github.com/openvinotoolkit/openvino.genai/pull/4139#issuecomment-5054376503
   - **Comment ID**: `5054376503`, posted 2026-07-23T04:31:25Z by `blairducrayoppat`
   - **Verified via**: GitHub REST API direct comment lookup; body diffed against draft —
     identical except a dropped trailing `*` (cosmetic; LA aware).

### SHA discipline (E4 compliance)

All cited SHAs verified against the PR commits API and file-path-filtered history before
appearing in any LA-handed artifact: head `8cf5e4502f330e423794aca8a1f7e299eed7c061`,
parent `5166cd3e4c719ee85924759a55c0f75a87d8e144` (contains the LA's MSVC fix), first
budget-capable commit `6ec58d95f55d`. Code line refs read at the exact commits. No
placeholders used.

### State at close

- Local checkout: `feat/thinking-suppression` @ `8cf5e450`; venv-build wheel
  `2026.4.0.0-50-8cf5e4502f3`; wheels archived in `dist/8cf5e450/` + `dist/5166cd3e/`;
  LA's superseded MSVC WIP in `stash@{0}` + patch backup; `pyproject.toml` Ninja line intact.
- Raw run JSONs: `docs/performance/probe_pr4139_v2_*_2026-07-22_*.json` (2 files).
- PR state at close: OPEN, `REVIEW_REQUIRED`, BEHIND master; ball with apaniukov (scope
  question) and the author.

### Next

LA-triggered, watching for: apaniukov's scope ruling on VLM budget support; author response.
Standing conditional offer: prototype real-prompt_ids threading on the VLM path + validate
on Arc 140V (only if in scope AND author wants help). BlarAI tie: #4139 remains the watched
blocker for the 35B consolidation decision (Vikunja #923, check-back 2026-07-30).

## E6 — Cycle 2 extension: tests + follow-up groundwork, same night (2026-07-22/23)

After the E5 close, same session, LA-directed:

1. **C++ unit tests written and validated** for `ThinkingBudgetTransform`: 8 tests appended
   to `tests/cpp/logit_filtering.cpp` in repo style, built via `-DENABLE_TESTS=ON`
   (`build-tests/`), **8/8 green at head `8cf5e450`**. Contested budget==0 corners
   deliberately not pinned (noted in-code). Patch held:
   `2026-07-22-cycle2-pr4139-review/pr4139-thinking-budget-cpp-tests.patch`.
   **Delivery gated** on: author responding / maintainer asking / branch stabilizing.
   Channel when triggered: "PR to the PR" from a fork of upstream (LA already has one).
   The test file change remains uncommitted in the local working tree by design.
2. **Wrap-up-sequence concept VALIDATED on Arc 140V** (`probe_pr4139_budget_wrapup.py`,
   two-phase, no C++ changes): tag-only control reproduces the budget-cap mush out-of-band;
   a wrap-up sentence + `</think>` yields a direct answer; boundary-truncation + wrap-up is
   cleanest and self-terminates (185/300 tokens). Phase-1 ID-identical to condition A
   (determinism verified). JSON: `docs/performance/probe_pr4139_wrapup_2phase_2026-07-22_22-21-33.json`.
3. **Follow-up design brief drafted** (local only, three explicit gates before any public
   move): `2026-07-22-cycle2-pr4139-review/followup-budget-usability-design-brief.md` —
   API sketch (`reasoning_wrapup`, empty-default back-compat), two-PR sequencing,
   upstream process requirements from `.github/CONTRIBUTING.md` (issue/RFC-first,
   AI Usage Policy compliance to read before any code PR).
4. (Non-workstream, same session: LA's GitHub profile + blarai-public +
   agentic-setup-public READMEs updated — vision film embeds, verified test counts,
   #4139 mention deliberately kept OFF the profile per LA's credit discipline.)

**Waiting on:** apaniukov's scope ruling on VLM non-chat budget support; author response
to the review + standing offers. LA-triggered as always.

## E7 — Cycle 3: collaborator invite accepted, same-day retest at cea6c5f2 (2026-07-23)

PR activity within hours of E5 posting: author replied warmly (reproduced the VLM finding
on Arc Pro B60; reports `get_prompt_ids()` EMPTY on that path, not pad-filled — not yet
reconciled with our tensor-level reading), apaniukov left a second inline suggestion
(reverse prompt scan), author implemented it same hour and re-requested LA's review.
Author sent LA a **collaborator invite (write) on `PlanteAmigor/openvino.genai`** —
the "option B" from their reply. **Accepted with LA's explicit go** (invitation 326672274;
`push:true` verified). Norms agreed with LA: author stays lead; announce before every push;
small scoped commits; no force-push; nothing on profile until merged.

1. Head moved `8cf5e450` → `cea6c5f2` (+ `edbd2428` auto-detect for budget — new comments
   in Chinese, needs translation before merge). Local checkout fast-forwarded; wheel
   `2026.4.0.0-52-cea6c5f2690` built + installed; archived `dist/cea6c5f2/`.
2. **Full matrix re-run on Arc 140V:** the ONLY behavioral delta old→new is C0
   (budget, no ids): validate() error → clean run, ID-identical to explicit-ids budget
   runs (§4b fix confirmed). All other cells full-ID-identical. VLM budget no-op
   unchanged → apaniukov scope question stands. Record:
   `2026-07-23-cycle3-pr4139-collab/measurement-record-cea6c5f2-vs-8cf5e450.md`.
3. **C++ tests updated 8 → 11** for the reverse-scan semantics (trailing pre-count,
   last-token-wins, DONE re-arm, budget==0/closed-block now pinned as author-confirmed
   deliberate). **11/11 green; full suite 564/566** (2 fails = env-gated suites).
   Un-pinned on purpose: trailing ≥ budget still admits one token (F12 — flag as question).
4. First collaborator commit prepared locally (tests only). **Delivery: announce-comment
   draft + push command read back to LA; nothing pushed or posted without explicit go.**

**Waiting on:** LA's go on (a) posting the announce comment, (b) pushing the test commit;
then apaniukov's scope ruling as before.

### E7 addendum — delivered (2026-07-23 ~14:33Z, LA's explicit go after diff review)

- **First collaborator commit pushed:** `f90cc87525d1a7f48172141e108c39cda92b4a40`
  ("Add ThinkingBudgetTransform unit tests for prompt-scan state machine", test-only,
  +203 lines) → `PlanteAmigor/openvino.genai` `feat/thinking-suppression`; verified as
  PR #4139 head (10 commits). LA held the push pending patch review first; sequencing
  conflict (draft said "I've pushed" while push was held) caught and resolved before
  anything went out.
- **COMMENT-type review posted** as LA via API (explicit go): review `4765132029`,
  14:33:18Z — retest results (C0 auto-detect confirmed; all else ID-identical; scope
  question unchanged), test-commit announce, F12 edge raised as author's-call question,
  Chinese-comment translation offered. Verified: LA cleared from requested_reviewers
  (5 Intel reviewers remain).
- Body archived: cycle-3 dir `pr4139-collab-announce-draft.md`; patch:
  `f90cc87-thinking-budget-tests.patch`.

**Waiting on:** author's response (F12 edge, translation offer), apaniukov's scope ruling,
upstream CI on f90cc87. LA-triggered.

### E7 addendum 2 — adversarial verification + correction (2026-07-23 ~15:05Z)

LA requested full adversarial verification post-delivery (worried about errors). Independent
subagent (upstream-review skill, fresh context) re-derived everything from primary sources:
- **Verdict: work sound.** All 11 test traces entailed by actual code at f90cc87 (re-run
  independently, 11/11 green); all ID-level measurement claims verified; SHAs, mechanics,
  identity, tone all clean. "(empty) prompt ids" VERIFIED with independently-derived root
  cause: PA/CB adapter path populates `original_prompt_ids_list` only under
  `is_prompt_lookup()` (`pipeline_base.cpp` L425–428) → `has_valid_prompt_ids` false
  (`pipeline_impl.cpp` L556) → SequenceGroup embeds branch leaves `m_prompt_ids` empty.
  Our earlier pad-filled reading was of the untaken stateful SDPA path.
- **One real flaw:** "full suite passes locally" overclaim (actual 564/566; 2 pre-existing
  env-gated gtest guards). Also noted: upstream CI on f90cc87 still `action_required`
  (fork workflows await maintainer approval) — local runs are sole validation so far.
- **Corrected on our terms (LA's go):** comment `5060021475` (15:05:33Z) — precision
  correction + the full prompt-ids root-cause trace (answers author's open "didn't have
  time to trace"; credits their debug print; routes fix location to CB path, scope still
  apaniukov's). Body archived in session scratchpad; verification agent ab80034ba51e75eb8.

**Waiting on:** author response, apaniukov scope ruling, maintainer approval of CI runs.

### E7 addendum 3 — author accepted the commit + took the translation offer (2026-07-23 ~16:35Z)

Within ~90 min of our correction/trace comment, the author pushed twice (no thread reply):
- `87acf7b8` "Translate auto-detect comments from Chinese to English" — took our offer and
  did it themselves. Verified: comments-only (11+11 / 16+16 in the two `src/python/*.cpp`
  binding files), translations faithful and idiomatic, zero logic change.
- `92e62812` merge commit ("Merge remote-tracking branch 'fork/feat/thinking-suppression'")
  — the author pulling our pushed commit into their local branch. **Our commit `f90cc875`
  is preserved as an ancestor of head** (compare API: ahead 2, behind 0) and **all 11
  ThinkingBudgetTransformTest cases are present in the file at head**. PR now 12 commits.

Tests provably unaffected by the two new commits (only `src/python/*.cpp` changed between
f90cc87 and 92e6281) — no rebuild needed. Local checkout fast-forwarded to `92e6281`.

**Credit mechanics — verified empirically (matters for LA's accreditation goal):** upstream
master is uniformly squash-merged (single-parent commits titled "... (#NNNN)"), and squashed
commits DO carry `Co-authored-by:` trailers for non-PR-author commits — confirmed on
`ad302d87` (credits Artur Paniukov). So on merge, LA should land as **co-author of the
squashed #4139 commit on openvino.genai master**, which GitHub counts in the contributors
graph. Residual risk: the merging maintainer edits the squash message and drops trailers —
not worth raising publicly (asking for credit reads badly); just be aware.

**No action taken or needed on-thread** (author asked nothing; adding "thanks for merging"
to a 35-item PR before maintainer review is noise). Still open: F12 edge question, apaniukov
scope ruling, CI approval (still only `triage` on the new head), branch BEHIND master.

## E8 — Contribution strategy: landscape sweep + #4035 cross-check + work queue (2026-07-23)

LA asked (a) where upstream effort pays off most for BlarAI, (b) status of his own feature
requests, (c) to cross-check model_server#4035 against the coder-swap notes. Three research
agents + a coder-swap memory mine. Key correction: **model_server (OVMS) is NOT irrelevant —
it is BlarAI's coder serving layer** (30B-A3B on `:8000`, `--target_device GPU`, via
`agentic-setup/scripts/start-llm.ps1`). Earlier "not relevant" call was wrong (reasoned, not
verified); corrected to LA.

**#4035 verdict — BlarAI is a POSITIVE Lunar Lake data point, not a victim.** The 30B coder
loads on Arc 140V GPU to a SINGLE ~15 GB footprint, 20/20 runs 0 errors, ~30.5 tok/s. The
bug's dual CPU+GPU staging IS visible on cold load (Committed→29 GB, Available→67 MB) but
survivable via pagefile-backed commit limit + 87% shared-mem override; warm compiled-kernel
cache eliminates it. Caveat: our data is OVMS 2026.2; reporters are 2026.3/2026.4. usm split
measured on 14B, inferred for 30B. Evidence: PERFORMANCE_LOG.md:1252/1263/2325,
benchmark_ovms_coder-30b_2026-06-29, FIELD_NOTES.md:286.

### Contribution work queue (drafts held; GPU runs serial & LA-gated)

READY TO POST (drafts on disk, cycle-3 dir):
- `draft-model_server-4035-lunarlake-datapoint.md` — LNL positive data point + survivable-
  transient diagnosis + offer to capture usm/current-version. Postable on 2026.2 data now.
- `draft-genai-4091-kvcache-followup.md` — data-led nudge on LA's own KV-cache FR (existing
  2026.2.1 prefill numbers: 16K→46s, 32K INT8→159s, 32K FP16→369s cold TTFT). Cadence OK
  (last activity 07-09). New task added by LA this session.

BLOCKED (watch-only):
- #4139 VLM-path prompt_ids fix — gated on apaniukov scope ruling. No action until ruled.

GPU-BOUND MEASUREMENT RUNS (strictly SERIAL — single iGPU, one model resident at a time;
each needs a GPU window + LA go):
  1. #4035 fresh 30B `GPU_MEMORY_STATISTICS` capture (usm_host vs usm_device at cold-load
     peak) — makes the usm claim direct not inferred. Small run on existing 2026.2. Optional
     stronger version: repeat on a current OVMS 2026.3/2026.4 install (same-version data pt).
  2. #4091 fresh prefill sweep (14B cold prefill × context/precision) — ~20 min; optional,
     nudge is fine on existing numbers.
  3. cache-flip experiment — text-only model, N≥3 cold + N≥3 warm, to confirm/kill the
     CACHE_DIR answer-flip before it's fileable. Serves BlarAI directly (caching currently
     OFF as a tax).

Parallelism note: drafting is done (this turn, no GPU). All measurement runs are serial on
the one iGPU. #4139 parallelizes trivially (external wait). So the only real scheduling
decision is the ORDER of the three GPU runs and which drafts post now vs after a run.

## E9 — Measurement session + two upstream posts (2026-07-23 afternoon)

LA cleared a GPU window (AO stopped, box free); the parallel BlarAI session had no competing
work. Ran the serial queue on Arc 140V, then posted two contributions. GPU-timing note logged
below (methodology).

**Posted (both via API as LA, explicit go each):**
- **model_server#4035** comment `5063034912` — Lunar Lake positive data point. Direct 30B
  `GPU_MEMORY_STATISTICS`: `usm_host` 15.06 GiB / `usm_device` 0 / `cl_mem` 0, on BOTH
  released genai 2026.2.1 AND from-source 2026.4.0 dev (PR#4139 build) — version-stable
  allocation → failures elsewhere are older-hardware, not version. Transient reframed
  honestly (variable spike, one-time load/compile staging, NOT persistent doubling). LA
  requested a pre-post critical re-read; it caught + fixed 2 real issues ("matched to the
  byte" → within ~0.3 MB; over-attributed transient cause → honest variability framing).
- **openvino.genai#4091** comment `5062934426` — data-led follow-up on LA's own KV-cache FR.
  Used the clean original prefill numbers (16K 46s / 32K u8 159s / 32K fp16 369s); NVMe
  restore-time argument sharpened (~1s vs 159-369s). Cadence-appropriate, arch-review
  acknowledged.

**BlarAI-internal conclusions (no config changed — LA owns those calls):**
- **14B compile cache: leave OFF.** June DEC probe (2026-06-03, real spec-decode config)
  already showed output byte-identical but warm≈compile (11s→9s) for 9 GB — negligible. My
  earlier "24× speedup" was an ERROR (compared cache-write-cold to warm-read on a plain
  pipeline). Corrected. Existing `CACHE_DIR=""` is right.
- **Cache-flip scare CLOSED.** Text (14B): cold≡warm byte-identical. Production VLM
  (Qwen3-VL-8B): cold≡warm byte-identical. The 2026-07-22 flip was a candidate 26B eval
  model's nondeterminism, not a cache bug. Docs: `ov_cache_answer_flip_2026-07-22/FOLLOWUP_text_2026-07-23.md`.
- **VLM is the better caching candidate** (warm 2.6s vs 15.8s compile; smaller cache) — worth
  revisiting once the new NVMe (Crucial P310, 7100 MB/s) is installed and disk isn't tight.

**Methodology note (for future benchmarking):** redirecting `LOCALAPPDATA` to protect disk
gives the GPU driver a COLD kernel cache and inflates prefill timing (32K u8: 243s redirected
vs 217s clean vs 159s original clean-cooldown) — do NOT redirect for timing runs; the redirect
is fine for memory/allocation and output-determinism runs. The load transient is likewise
cache/thermal-sensitive (23–31 GB peak same weights).

**Cleanup:** OVMS not running (none started); scratch caches reclaimed; box left clean for
the 23:00 nightly to boot its own fresh 14B. Raw JSONs in `docs/performance/`
(capture_4035_usm_*, kv_cache_sweep_*2026-07-23*, flip_*_2026-07-23).
