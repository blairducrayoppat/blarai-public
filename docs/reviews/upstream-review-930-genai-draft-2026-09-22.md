# Upstream review — draft genai issue, #930 §6.1 (a3946c58) — 2026-09-22

Reviewer: independent session; did not author the draft. Nothing here has been posted.

## 1. Verdict

**Not postable yet.** The rewrite fixed the register; it did not fix the substance. The headline
claim, "the same pipeline, in one process, without reloading, gives different results run to run",
is contradicted by our own same-day probe at the byte level. The suite counts include 10 cases that
never run the model. The injection case that the question rests on only moved with prefix caching
on. And the triager's likely first reply (the #4476 precision knobs) is a test we can run tonight.

## 2. What I verified, and how

| Claim in draft | Check | Result |
|---|---|---|
| @diego-villalobos said the GPU plugin does not guarantee bit exactness "even for the same usage" | `gh api .../issues/4367/comments` | **Holds**, verbatim (2026-09-04). He is not tagged as a member (`author_association: NONE`); he filed the internal ref 194183 |
| #4367's paths were each bit-stable across restarts | #4367 body + marfrit 08-31 | **Holds** |
| marfrit's two-tokens-in-one-call observation | marfrit 09-04 | **Holds**; he pinned it to `ocl::gated_delta_net::ref` |
| "30-case behavioural suite", 30/30 vs 30/28/28 | `evals/golden/agentic.jsonl` | **Wrong.** `ag-det-*` (10 cases) are `mode: offline`, `scripted`. The model never runs for them. Model-driven cases number 20: 14B 20/20/20, 35B 20/18/18 |
| Prefix caching ruled out, "a *different* three" moved | `prefix_cache_determinism_2026-09-22_18-47-58.json` | **Overstated.** OFF: chain-01 and idem-01 still moved; only inject-01 → empty-01 swapped. **`ag-inject-01` was pass/pass/pass with caching off** |
| Cold start ruled out by one discarded warm-up | `probe_35b_greedy_determinism_2026-09-22_04-13-38.json` (2026.2.1) | **Not established.** One prompt, 4 calls × 2 loads: call 1 differs, calls 2–4 byte-identical, and the whole sequence is identical across both loads. So when the same prompt repeats, the warm pipeline is bit-stable. Warming up on one prompt says nothing about other prompt shapes or about what earlier calls leave behind |
| Identical input across runs | spread JSONs; `evals/suites/agentic.py` | **Never measured.** Both JSONs record pass/fail only: no rendered prompt, no token-id hash, no output text. The unstable cases use only the fake `search_knowledge` tool, so the likely inputs are fixed. That is an inference, not a measurement |
| Control arm "bit-stable" contrast | same | **Not like-for-like.** The 14B's verdicts were stable. Its bytes were never compared |
| "Same process, minutes apart, identical code" | spread JSON `method`, `not_modelled` | **Unsupported.** The record says "ONE loaded model per arm". The two arms use different pipeline classes and decoding paths, and the draft itself lists those as unbisected |
| Setup: OpenVINO GenAI 2026.2.1 | `.venv` = 2026.2.1.0-3123; `.venv-2026.4` = 2026.4.0.0-3407; neither spread JSON records a version | **Unverified.** The 2026.4 plan says ".venv-2026.4 carries all measurement". Which one ran is not recorded |
| Model in scope | `models.ts` at tag `2026.2.1.0` | **Supported**: Qwen3.6-35B-A3B is listed under Qwen3.5 architecture. Their `test_vlm_pipeline.py` at that tag runs only `tiny-random-qwen3.5`, with no GPU case |
| Prior art | `gh api search/issues` | **Missed #4476** (open): greedy spec-decode output differs on GPU. Maintainer @apaniukov (09-18) named `KV_CACHE_PRECISION`, `KEY_CACHE_QUANT_MODE`, `DYNAMIC_QUANTIZATION_GROUP_SIZE`. The reporter got exact output with KV f16 + DQ 0. Our `default.toml` has `kv_cache_precision = ""` |
| Operator's standing on this model upstream | commenter search | **His 2026-07-09 comment on #3937 (same model family) stands unretracted.** The journal records it as API misuse |
| Length | `wc -w` | 283 words (#4367 body: 195) |

## 3. Errors, risks, gaps — most important first

1. **DEFECT — the new claim is not what our data shows.** On one repeated prompt the warm pipeline
   is byte-deterministic, and so is the call sequence across loads (the 04:13 probe). "Same pipeline
   gives different results run to run" therefore holds only for verdicts across a 20-case sequence.
   So either the inputs differ between runs, or the output depends on what ran earlier. If it is
   call history, that is marfrit's mechanism, and the case becomes stronger and more specific. Our
   single-prompt probe is the most useful thing we could hand them, and the draft leaves it out.
2. **DEFECT — the question rests on the one case prefix caching explains.** `ag-inject-01` moved
   1 time in 6 runs overall, and only with caching on. The draft says caching is "ruled out" and
   then leads its ask with that case. At n=3 per arm, "ruled out" and "relocates like randomness"
   are both below measured noise. What survives: chain-01 and idem-01 move with caching on and off.
3. **DEFECT — 30 should be 20.** A maintainer who accepts the offered suite finds 10 scripted cases
   straight away. The 14B's perfect score is then partly cases that cannot vary.
4. **DEFECT — no byte-level evidence exists to share.** "Happy to share per-case records" means
   pass/fail rows. Missing: rendered-prompt hashes and output hashes per call per run. These are the
   direct check for input identity (standing rule: a direct check exists, so do not reason from a
   proxy).
5. **DEFECT — #4476 not addressed.** @apaniukov's knobs are the likely first reply, and they take
   one GPU session to test on our box. Filing without trying them asks the maintainer to do our
   first step.
6. **DEFECT — setup does not meet community grade.** Missing: GPU driver version (it moved
   8826 → 8991 → 8831 in September, per the 09-21 disposition), the exact export id, KV-cache and
   scheduler config, and which runtime ran. 2026.4.0 is released, and #4367 was on 2026.4.
   Measuring only on 2026.2.1 invites "please retry on latest".
7. **DEFECT — no "What I checked" paragraph.** It needs four items: the supported-model listing at
   the release tag, their test coverage (tiny-random only, CPU), #4367/#4476, and a known-issues
   check. I verified the first three here; the author must cite them in the draft.
8. **RISK — the ask over-generalises.** "This class of model cannot sit behind the policy gate at
   all": the no-bit-exactness statement covers the GPU plugin, which the 14B also runs on. A
   maintainer will say the same reading applies to the brain we ship. Scope the question to what
   was measured.
9. **RISK — sequencing.** The same account is filing about this model family while the #3937
   comment of 07-09 stands uncorrected. The correction should go up first.
10. **Minor.** The readiness doc's opening says "Intel has already said"; attribute it to the
    #4367 triager. The draft could name `ocl::gated_delta_net::ref` when citing marfrit, since he
    did.
11. **Decision (operator's) — AI-assistance disclosure.** genai has no CONTRIBUTING.md. The
    workstream precedent (`PR_34617_DESCRIPTION_PASTE.md`) discloses. The draft does not.

Engagement track: an issue asking a question is the right shape. No implementation is claimed or
left open, so there is nothing to invite someone else to take.

## 4. The operator decision

Nothing to decide yet: the draft goes back for rework, which is technical and belongs to the
author. When the rework returns, the decisions will be (a) go/no-go on the #3937 correction under
his name, to be posted before this issue, and (b) whether to include the AI-assistance line.
Recommendation on both: yes.

## 5. Drafted response to send back to the authoring session

> Review of §6.1 at a3946c58, independent session. **Not postable.** The register is fixed; the
> substance needs rework and one GPU session. Verdicts and instructions only; the wording is yours.
>
> Confirmed correct: the @diego-villalobos quote (verbatim, #4367, 09-04), #4367's paths being
> bit-stable across restarts, marfrit's two-tokens-in-one-call mechanism (he pinned it to
> `ocl::gated_delta_net::ref`), and Qwen3.6-35B-A3B being listed as supported at tag 2026.2.1.0.
>
> Defects, all to fix before this returns:
> 1. Your own `probe_35b_greedy_determinism_2026-09-22_04-13-38.json` shows the warm pipeline is
>    byte-identical on a repeated prompt, and the call sequence is identical across loads. The
>    headline "different results run to run" contradicts it as stated. Reconcile the two and put
>    the probe in the report.
> 2. `ag-det-*` are scripted, offline cases: 10 of the 30 never run the model. Report the 20
>    model-driven cases.
> 3. `ag-inject-01` was stable with prefix caching off, and two of the three moving cases were the
>    same in both arms. The ask cannot lead with inject-01 while the draft says caching is ruled
>    out. At n=3 per arm, neither "ruled out" nor "relocates randomly" is established.
> 4. No input or output identity was recorded. Re-run with a hash of every rendered prompt and every
>    output, per call, per run. Report byte-level identity for both arms, not verdicts.
> 5. Address #4476. Run the 35B arm with `KV_CACHE_PRECISION=f16` and
>    `DYNAMIC_QUANTIZATION_GROUP_SIZE=0` before filing.
> 6. Record which venv ran the spread (both 2026.2.1 and 2026.4.0 are installed and neither JSON
>    says). Repeat on 2026.4.0. Add the driver version, exact export id, KV/scheduler config.
> 7. Add a "What I checked" paragraph with paths/URLs: supported-model listing at the tag, their
>    test coverage (tiny-random qwen3.5, no GPU case), #4367, #4476.
> 8. Narrow the ask. The plugin statement covers the 14B too, so "this class of model" does not
>    follow from what was measured.
> 9. Draft the #3937 correction for the 07-09 comment. It goes up before this issue does.
> 10. Update the readiness doc and PERFORMANCE_LOG where they carry 30/30, "a different three" and
>     "cold start ruled out". Keep the wrong versions visible. Write a disposition record for this
>     review and run `scripts/verify_disposition.py`.
>
> Draft, don't post. Read the final text of both the issue and the #3937 correction back to the
> operator for an explicit go on each before anything goes public.
