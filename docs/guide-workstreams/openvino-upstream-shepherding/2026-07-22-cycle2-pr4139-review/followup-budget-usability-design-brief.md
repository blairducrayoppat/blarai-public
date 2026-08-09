# Design brief (DRAFT) — follow-up contribution: making `reasoning_budget_tokens` usable

*Status: local pre-PR planning document. NOT for posting. Started 2026-07-22 late evening,
while #4139 is still in review. Everything here is provisional on three gates (below).
Owner: Blair (`blairducrayoppat`). Per workstream charter, if this proceeds to code it
spins out into its own contribution workstream.*

## Gates (do not start public work before these resolve)

1. **#4139 lands or is clearly near-landing.** This contribution builds on its API; filing
   early splits maintainer attention and could stall the base PR.
2. **apaniukov's scope ruling** on VLM non-chat budget support (asked 2026-07-23, comment
   `5054376503`). The ruling decides whether a prompt_ids-threading fix is part of #4139,
   a separate PR-A here, or out of scope.
3. **Author's reception.** PlanteAmigor may want to build this themself — our standing
   offer was hardware + hands, their call. If they take the feature, this brief becomes
   support material we hand them, which is an equally good outcome.

## Problem statement (measured, cycle 2, 2026-07-22)

`reasoning_budget_tokens=N` mechanically works — the parent-commit run forced `</think>` at
exactly index 32 with no off-by-one — but the output is **unusable on naked-reasoning
models**: the forced tag landed mid-sentence ("…one kilobyte`</think>`") and the model
continued its numbered reasoning *after* the tag ("2. **Recall/Verify Knowledge**…").
The cap controls the tag position, not the model's behavior: nothing in the context tells
the model to conclude. Consumers splitting on the first `</think>` receive reasoning as
the "answer." (Full data: `measurement-record-8cf5e450-vs-5166cd3e.md`, finding F5.)

## Concept validation — two-phase wrap-up probe (2026-07-22, run `probe_pr4139_budget_wrapup.py`)

**RESULT: GO.** Raw JSON: `docs/performance/probe_pr4139_wrapup_2phase_2026-07-22_22-21-33.json`.
Same wheel (head `8cf5e450`), same hardware, greedy. Phase-1 determinism cross-check
passed: the 32-token reasoning prefix is **ID-identical to condition A's first 32** — the
two-phase method mirrors the in-band cap exactly.

| Cond | Continuation prompt | Result (sha) |
|---|---|---|
| T (tag-only control) | reasoning32 + `</think>\n\n` | **Mush** — "2. **Recognize the Core Concept**…" — continued numbered reasoning; reproduces the in-band C32-parent failure out-of-band (`e1016570`) |
| W (wrap-up) | reasoning32 + wrap-up sentence + tag | **Direct answer** — "The answer depends on whether you're using the **decimal (SI)** or **binary (IEC)** system…" (`72326872`) |
| WB (boundary + wrap-up) | boundary-truncated reasoning + wrap-up + tag | **Cleanest** — "The number of bytes in a kilobyte depends on the context: … 1,024 bytes…" AND self-terminated at 185/300 tokens (natural EOS — a complete answer, not a truncation) (`55f6d92a`) |

Wrap-up sentence used: `"\n\nConsidering my limited thinking budget, I'll answer directly now.\n"`.

The control (T) reproducing the mush proves both the methodology and the bare-tag problem;
W flipping to a coherent answer proves the wrap-up sentence is the active ingredient; WB's
natural EOS at 185 tokens is the strongest outcome — capped reasoning, complete answer,
clean termination. Note: the probe's automated `direct_answer` heuristic misclassified W
(lead didn't literally start with "The number of bytes") — human reading is unambiguous;
both the heuristic output and full texts are preserved in the JSON.

Caveat: one prompt, one model, greedy, single run. Sufficient for GO on a design brief;
the eventual RFC should sweep 2–3 prompts and note the model-family scope.

Technique under test (prior art: Qwen's own thinking-budget implementations; s1
"budget forcing," Muennighoff et al. 2025): when the budget trips, force a **wrap-up
sequence** — a natural-language sentence + `</think>` — rather than the bare tag, so
"conclude now" enters the model's context.

## Design (provisional)

**Recommended: wrap-up sequence forcing.**
- `GenerationConfig` gains `reasoning_wrapup` (string, default `""`). Empty string =
  current bare-`</think>` behavior → fully backward compatible, zero behavior change for
  existing users.
- Bindings tokenize the string once (same pattern as the existing `<think>` auto-detect)
  into internal wrap-up token ids ending with `thinking_end_token_id`.
- `ThinkingBudgetTransform`: FORCING generalizes from "force end_id" to "force the k-th id
  of the configured sequence" (a queue index). State machine otherwise unchanged; DONE on
  sequence completion. The 8 unit tests added tonight (`pr4139-thinking-budget-cpp-tests.patch`)
  extend naturally — sequence of length 1 ≡ current behavior, so they keep passing as-is.

**Optional add-on: boundary-aware forcing** — delay the trip until the next
newline/sentence token so the tag never lands mid-word. Cosmetic; include only if WB
measurably beats W, and note it costs up-to-a-few extra reasoning tokens past the budget.

**Rejected: soft logit bias on `</think>`** — unreliable by construction on models that
never emit the tag unprompted (Qwen3.5/3.6), which are exactly the problem models.

**Sequencing:** possibly two PRs — PR-A (thread real prompt_ids through the VLM non-chat
sequence group; only if apaniukov rules it in scope AND the author doesn't take it) and
PR-B (wrap-up feature). Never one combined PR.

## What "mature" means here (Blair's directive, 2026-07-22)

Complete-within-scope, not maximal-scope: motivation anchored in published measurements →
API proposal → working PoC → C++ unit tests + Python behavioral tests → hardware
validation on Arc 140V (the model family that motivated it) → docs + sample update →
AI-assistance disclosure. NOT: bundled refactors, extra config knobs (e.g. the
auto-detect asymmetry), or the redundant-`</think>` trade-off — those stay separate
conversations.

## Upstream process requirements (verified in `.github/CONTRIBUTING.md`, 2026-07-22)

- Fork-based PRs only (never push branches to upstream).
- pre-commit hooks required; Windows: `git config core.autocrlf input` first.
- Code style: match the file you're editing.
- **New features MUST have:** PoC (optimum-intel model prep + GenAI inference), an
  architectural review (API proposal for optimum-intel and GenAI, working PoC, CLI args
  if applicable, GenAI sample), or the PR is rejected. ⇒ **entry move is an issue/RFC
  with our measurements, not a cold PR.**
- Contributions using AI must comply with OpenVINO's AI Usage Policy — read it in full
  before any code PR (we disclose already; verify the policy's specific requirements).
- CI runs only after a developer approves the test run.

## Evidence inventory (already in hand)

- Cycle-2 measurement record: exact-N capping proof, mush demonstration, VLM pad-ids root
  cause, before/after on two builds.
- 8 green C++ unit tests for the current state machine (patch ready).
- Wrap-up concept probe (pending tonight).
- Standing rebuilt-from-source harness: cheap re-validation of any revision on Arc 140V.

## Open questions

- Where should the wrap-up string live: `GenerationConfig` (per-request) vs pipeline-level
  default? (Lean: GenerationConfig, matching the PR's existing fields.)
- Should the default be empty (bare tag, back-compat) or a sensible sentence? (Lean:
  empty default; docs recommend a string. Maintainers may prefer otherwise.)
- Multi-block interaction: does the wrap-up sequence re-arm per block? (Lean: yes,
  consistent with current re-arm semantics.)
- Does the same mush problem affect tag-emitting models (Qwen3-14B etc.)? Untestable on
  this machine today — flag honestly; the author has those models.

## Update — 2026-07-23 (cycle 3; supersedes stale lines above, gates UNCHANGED)

Context: LA accepted the author's collaborator invite (write on the fork); commit
`f90cc875` (test-only) delivered and is now PR #4139's head; correction + prompt-ids
trace posted (comment `5060021475`). Deltas for this brief:

1. **Motivation strengthened — author on record.** Replying to §4a (2026-07-23, comment
   `5056638921`): "mid-stream forcing on naked-reasoning models is inherently limited.
   Worth documenting." The minimal remedy (docs note) is now acknowledged upstream;
   this feature is the mature remedy. Cite that comment in the eventual RFC.
2. **Tests: no longer a held patch — delivered in-PR.** The "8 green tests (patch
   ready)" lines above are stale: now **11 tests, in the PR itself** (`f90cc875`),
   updated for cea6c5f2's reverse-scan semantics (trailing prompt tokens pre-count
   against the budget; end_id → DONE with re-arm; last think-token wins; budget==0
   closed-block pinned as author-confirmed deliberate). The extension argument holds
   unchanged: wrap-up sequence of length 1 ≡ current behavior.
3. **New design inputs from cea6c5f2 (reverse scan):**
   - Trailing pre-count means FORCING can begin at the very first generated token of a
     continue-final-message prompt — the wrap-up queue must work from index 0. (Same for
     budget==0: the whole wrap-up sequence forces from the start.)
   - Open F12 edge (asked on-thread, awaiting author): trailing count ≥ budget at
     construction still admits one generated token before FORCING. If the author adds a
     constructor check, the wrap-up queue design should start FORCING at construction too.
4. **PR-A is now precisely located** (verified trace, comment `5060021475`): the CB/PA
   adapter path fills `original_prompt_ids_list` only under `is_prompt_lookup()`
   (`pipeline_base.cpp` L425–428 @ f90cc87) → `has_valid_prompt_ids` false
   (`pipeline_impl.cpp` L556) → SequenceGroup embeds branch leaves `m_prompt_ids` empty.
   Fix = populate `original_prompt_ids_list` (or pass tokenized prompt into
   `add_request`) on the CB path. The old "pad-filled tensor" reading was the untaken
   stateful SDPA path. Still gated on apaniukov's ruling AND author preference.
5. **New relationship option for Gate 3:** LA is now a collaborator with a warm working
   relationship. A strong etiquette move when gates open: invite PlanteAmigor to co-build
   the follow-up (reciprocity — they invited us into theirs). Their Arc Pro B60 also
   covers the tag-emitting-model open question below.
6. Open-questions addendum: the author has hardware + models to test whether tag-emitting
   models mush too (their B60); ask rather than flag-untestable.

## Update — 2026-07-24 (cycle 4; gates STILL UNCHANGED, still parked)

Context: #4139 head moved cea6c5f2 → `4c0e8d6d`; LA's cycle-4 COMMENT review posted
(review `4770338001`, re-request cleared). Deltas for this brief:

1. **Design input #3 (cycle-3) is now RESOLVED upstream, not speculative.** The author
   added the construction-time forcing check the F12 edge asked for — `4c0e8d6d`: if
   `m_state == COUNTING && m_count >= budget` after the reverse scan, go straight to
   FORCING. **Design consequence for the wrap-up feature:** the wrap-up queue must emit
   from the very first generated token whenever the budget is already spent at
   construction (trailing count ≥ budget, and the budget==0 case) — i.e. FORCING at
   construction means "begin the wrap-up sequence at index 0," not "force one bare tag."
   The length-1 back-compat identity still holds.

2. **Base PR edge cases now settled + hardware-confirmed.** LA rebuilt #4139 with and
   without the 5-line fix on Arc 140V (Qwen3-14B INT4, GPU, greedy) — the wrap-up feature
   now builds on a base whose construction-time behavior is pinned and measured, one less
   moving part. Record: `2026-07-23-cycle4-pr4139-4c0e8d6d-review/DEVICE-PROBE-before-after.md`.

3. **New — narrow data point on the open "do tag-emitting models mush?" question.** The
   cycle-4 probe forced `</think>` on **Qwen3-14B** (a tag-emitting model) at budgets
   0/1/2/3 and the model pivoted cleanly to a direct answer every time — e.g. budget=1
   after the fix: `"</think>\n\n2 + 2 = 4."`, no trailing reasoning, no mush.
   **DO NOT over-read this.** The prompt was trivial single-step arithmetic
   ("What is 2+2?") with a 0–3 token budget — the *opposite* regime from the brief's mush
   finding (Qwen3.6-35B, mid-complex multi-step reasoning, budget 32). All it shows is
   that a tag-emitting model on a trivial prompt with a tiny budget wraps up fine; it says
   nothing about mid-complex-reasoning truncation, which is where mush appears. The open
   question stands — the proper test is still a substantive prompt + larger budget on a
   tag-emitting model (author's B60), exactly as item 6 above says. Logged here only so
   the RFC doesn't claim "untested on tag-emitting models" when a (weak) point now exists.

4. **Gates unchanged, and Gate 1 is measurably far off.** As of 2026-07-24 #4139 is
   `REVIEW_REQUIRED` with zero approvals, all CI still `action_required` (never run on any
   commit), branch `BEHIND` master, and apaniukov's VLM-scope ruling still not posted. So
   the base is not near-landing — keep this fully parked; do not open any public work.
