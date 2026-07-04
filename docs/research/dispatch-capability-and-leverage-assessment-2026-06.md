# Dispatch capability & leverage assessment (2026-06-26)

A grounded answer to the strategic question: *is there a fundamental flaw in the headless-coding
dispatch's design, is there engineering we should be doing but aren't, or are the local-runnable
models simply not smart enough?* Two independent research passes (capability ceiling; high-leverage
techniques), every headline number re-fetched against primary sources. Citations inline.

## The honest one-paragraph answer

The **architecture's philosophy is right** — a deterministic build/test gate as the final JUDGE with
the LLM/VLM as a SIGNAL is exactly the asset that makes a weak local model usable, and most systems
*lack* it. But there is a **strategic misallocation**: the system has invested in the **review/selection
side** (three review surfaces — 30B self-review, cross-model 14B critic, VLM design loop), which the
evidence says is **saturated** (more reviewers ≈ +0), while leaving the **single highest-leverage local
lever — best-of-N parallel sampling with the gate as selector — entirely unpulled**. Underneath that,
the models **are** a real ceiling: a ~30B local coder autonomously building a working app end-to-end
succeeds ~**15-35%** for a simple app and **single digits** for multi-feature, and it **degrades steeply
with task length** (the best-evidenced finding in the field). So it's *all three* of your hypotheses at
once — but in a specific, fixable ratio: **route around the model's worst weakness (long-horizon
self-correction) by spending your retry budget on parallel independent samples, not more reviewers.**

## 1. Are the models smart enough? — Partly no, and the limit is *task length*

**The runnable class (what fits in 31 GB at INT4/INT8):**

| Model | size | SWE-bench Verified | note |
|---|---|---|---|
| Devstral-Small-24B (v2) | 24B dense, INT4 ~13 GB | **~47-68%** (vendor, best-scaffold) | purpose-built for agentic harnesses (OpenHands) |
| Qwen3-Coder-30B-A3B | 30B/3.3B-active MoE, INT4 ~17 GB | **~51.6%** (100-turn OpenHands) | fast, low active-param |
| Qwen2.5-Coder-32B | 32B dense, INT4 ~18-20 GB | **32.5%** (third-party) | base is non-agentic |

Sources: [mistral.ai/devstral-2](https://mistral.ai/news/devstral-2-vibe-cli/),
[HF Qwen3-Coder-30B](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct),
[llm-stats Qwen2.5-Coder](https://llm-stats.com/models/qwen-2.5-coder-32b-instruct).

**The frontier:** ~**80-88%** single-issue SWE-bench Verified (Opus 4.5 80.9%, Opus 4.8 ~88.6%, GPT-5.1-Codex-Max
77.9%) — benchmark is *saturating* at the top ([anthropic Opus 4.5](https://www.anthropic.com/news/claude-opus-4-5),
[Vals.ai](https://www.vals.ai/benchmarks/swebench)). **Gap = ~15-35 points single-issue, and it WIDENS on
hard long-horizon suites:** SWE-bench Pro (standardized scaffold, less inflation) = frontier ~59% vs even
*giant* open MoEs ≤39%, GLM-4.6 just 9.7% ([Scale SWE-bench Pro](https://labs.scale.com/leaderboard/swe_bench_pro_public)).
The near-frontier open scores all belong to 100B-1T MoEs that **do not fit in 31 GB** — they are off the table.

**The decisive finding — degradation with task length (this is what "star not rocket" and "spun 60 min" actually were):**
- METR: ~**100% success on tasks under 4 min, <10% over ~4 hours**; the reliable-task-horizon scales with model
  capability, so a small model's horizon is *structurally short* ([metr.org](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/), [arXiv 2503.14499](https://arxiv.org/abs/2503.14499)).
- Error compounding is **mathematical**: constant per-step failure → success ≈ p^N. A 97%/step model finishes a
  50-step task ~22% of the time; 90%/step → ~0.5% — same one-shot "quality," wildly different long-horizon outcome
  ([Toby Ord, arXiv 2505.05115](https://arxiv.org/abs/2505.05115)).
- Open-weight matches **GPT-5 on single-tool use** but collapses on long-horizon planning (GPT-5 10% vs best
  open-weight **0%**) — AgentFloor ([arXiv 2605.00334](https://arxiv.org/abs/2605.00334)).
- **Weak models fail specifically at self-correction** — they enter "error traps" and stay stuck while strong
  models recover; recovery rate *declines* with horizon ([SciAgentGym arXiv 2602.12984](https://arxiv.org/html/2602.12984),
  ["Beyond pass@1" arXiv 2603.29231](https://arxiv.org/abs/2603.29231)).

**End-to-end app build (direct measurements):** E2EDev — best framework ~30-50% requirement accuracy, Qwen2.5-70B
35.8%, Qwen2.5-7B 22.4% ([arXiv 2510.14509](https://arxiv.org/abs/2510.14509)); Commit0 — best 15% tests, 0 libraries
fully ([arXiv 2412.01769](https://arxiv.org/html/2412.01769v1)); BaxBench — 62% of even the best model's solutions
incorrect/insecure ([baxbench.com](https://baxbench.com/)). **Interpolated ~30B end-to-end "app that runs" ≈ 15-35%
simple, single digits multi-feature.**

**Quantization makes the agent loop worse than the single-shot number suggests:** INT4 long-context drop up to **59%
vs 0.8% at INT8** ([arXiv 2505.20276](https://arxiv.org/abs/2505.20276)); INT4 ~doubles per-step "flips" vs INT8
([arXiv 2407.09141](https://arxiv.org/abs/2407.09141)); OpenVINO itself treats INT8 as the accuracy-safe default and
INT4 as data-aware-recovery-only ([OV docs](https://docs.openvino.ai/2025/openvino-workflow/model-optimization-guide/weight-compression/4-bit-weight-quantization.html)).
**Implication: prefer INT8 for the CODER in the agent loop where 31 GB allows** (24B INT8 ~25 GB fits; 30B-A3B INT8 ~31 GB is tight).
*Caveat: no published study runs a quantized model through a full agent trajectory; this is assembled from adjacent evidence.*

## 2. Is there a fundamental flaw? — Not in the philosophy; yes in the allocation

**Right (keep):** the deterministic gate as final judge. Without a *true* execution verifier, selection plateaus after a
few hundred samples; *with* one you can cash in the best-of-N coverage curve. This system has the rare asset
([CodeMonkeys](https://scalingintelligence.stanford.edu/blogs/codemonkeys/)).

**The flaw:** effort went to the **saturated half**. METR measured **+26pp from base-model post-training vs only +8pp
(statistically insignificant) from scaffolding/elicitation** on top ([metr.org](https://metr.org/blog/2024-03-15-measuring-post-impact-enhancements/));
Anthropic ("add complexity only when it demonstrably improves outcomes") and Cognition ("don't build multi-agents — very
fragile") both warn elaborate orchestration buys fragility, not score
([anthropic](https://www.anthropic.com/research/building-effective-agents), [cognition](https://cognition.com/blog/dont-build-multi-agents)).
**This system already has three review surfaces.** A fourth is low-leverage. The bottleneck at the weak end is
**generation coverage** (CodeMonkeys: 69.8% reachable vs 57.4% captured) — which you cash in by generating MORE
candidates, not reviewing the one harder.

**The deeper mismatch:** the serial retry loop (re-fix the last failure 2-3×) asks the weak model to do the one thing
it's *worst* at — recover from its own error. Best-of-N (parallel **independent** samples) routes around that weakness
entirely: take N fresh attempts, let the gate pick the winner.

## 3. The engineering you're missing — ranked by evidence

1. **Best-of-N parallel sampling, gate as selector — MISSING, highest leverage.** A *weaker* open model (DeepSeek-Coder-V2)
   went **15.9% → 56%** on SWE-bench Lite from 1→250 samples, **beating the 43% frontier single-sample SOTA**; coverage
   scales log-linearly over 4 orders of magnitude ([arXiv 2407.21787](https://arxiv.org/abs/2407.21787)). Cost framing for a
   LOCAL box: 5 cheap samples beat one frontier call on **both** cost and solve-rate — and locally the marginal sample is
   *electricity, not API dollars*. CodeMonkeys: **57.4% of SWE-bench Verified**, selection only 5.8% of spend
   ([arXiv 2501.14723](https://arxiv.org/abs/2501.14723)). **You already own the expensive part (the verifier); you're just
   not feeding it N diverse candidates.** Spend the *existing* retry budget on independent samples, not correlated re-fixes.
2. **Gold/spec tests FIRST, fed to the coder — PARTIAL.** Lifts weak models most: Llama-3-70B MBPP **46.4% → 75.9% (+29.6pp)**,
   *"more pronounced for less performant models"* ([arXiv 2402.13521](https://arxiv.org/html/2402.13521)). **Hard caveat: the 30B
   must NOT author its own oracle** — self-generated valid reproduction tests only ~8-12% on hard cases
   ([arXiv 2412.02883](https://arxiv.org/abs/2412.02883)). Use spec-derived/human gold tests as coder *input*; it also sharpens
   best-of-N selection precision (synergy with #1).
3. **Fixed structured decomposition (Agentless-style), NOT free-form self-planning — LIKELY ALREADY HAVE (the seeded scaffold).**
   Simple localize→repair→validate beat free-form agent **32.0% vs 18.3%** at a third the cost on fixed weights
   ([arXiv 2407.01489](https://arxiv.org/abs/2407.01489)). Caveat: a planner *weaker than* the executor *hurts* (COPE: 73.8%→69.6%
   with a 1B plan) — so keep decomposition a fixed pipeline, never a 30B free-planning stage ([arXiv 2506.11578](https://arxiv.org/abs/2506.11578)).
4. **Narrow-domain fine-tuning — highest ceiling, lowest practicality now.** Qwen2.5-Coder-32B **7.0% → 20.6% → 32.0%** (491
   trajectories + verifier) ([arXiv 2412.21139](https://arxiv.org/html/2412.21139)); DeepSWE (Qwen3-32B RL) 42.2%→59% with
   test-time scaling. But all rode *executable-test trajectory data* a GUI/C# domain lacks off-the-shelf, and SFT degrades
   out-of-domain. Defer.

**Provably not worth more investment:** a fourth review/critic layer or richer multi-agent orchestration (see §2).

## 4. Model & precision choices to evaluate

- **Coder model:** if not already on one, evaluate **Devstral-Small-24B** (purpose-built for agentic harnesses, ~47-68%)
  or **Qwen3-Coder-30B-A3B** (~51%, fast MoE). Model choice is itself a lever; a generic 30B is not the same as an
  agentic-tuned one.
- **Precision in the agent loop:** prefer **INT8** for the coder where the 31 GB budget allows (24B INT8 ~25 GB fits) — INT4
  bites hardest exactly on the long trajectories this system runs.

## 5. The reframe that makes the whole thing work

**Architect for the model's actual horizon.** The model is *near-frontier on short, well-scoped, test-gated steps* and
*falls off a cliff on long unattended runs*. So: shorter steps, more checkpoints, deterministic verification between each,
and treat fully-autonomous end-to-end app builds as the **exception, not the expected path**. You already do a version of
this (scaffold seeding, bounded iteration) — lean harder into it.

**Why this compounds (the portfolio/decades framing):** the levers that compound are **generation coverage + verification**
(the gate, the acceptance tests, best-of-N), because as local models climb the capability/horizon curve (METR: the reliable
horizon **doubles ~every 7 months**), a harness built to extract maximum coverage from whatever model is resident *rides that
curve automatically*. The review surfaces don't compound — they're already saturated. So the recent critic/VLM work isn't
wasted (they're real, cheap signals for things the gate can't judge — cross-model de-bias, visual quality), but the **next**
marginal build should go to generation coverage, not a fourth reviewer.

## 6. Recommendation (ACCEPTED — LA-approved 2026-06-26)

**Status: ACCEPTED by the LA 2026-06-26.** Tracked as Vikunja **epic #688** ("Dispatch generation-side
re-weight") with children **#689** (best-of-N), **#690** (spec-tests-to-coder), **#691** (right-size
envelope), **#692** (model eval at INT8). **Sequenced AFTER** the current #687 queue finishes (#6 design
loop / #685 + #9 critic live-verify). Item 5 (freeze the review side) is an accepted standing guardrail,
recorded in the #688 body rather than as a build ticket.

Re-weight the roadmap from review-side to generation-side:
1. **Build best-of-N**: N independent coder samples per step (start N=3-5), deterministic gate selects the first green (or the
   best partial). Replaces — does not add to — the serial retry loop. First check: can the OVMS/OpenVINO-GenAI serving stack
   batch N generations, or must they run sequentially? (Sequential is still worth it; batched is cheap.) This is the single
   highest-evidence move and it's nearly free locally.
2. **Feed spec-derived gold tests to the coder** as input (acceptance.py already generates spec-blind tests — wire them in
   front of generation, not only as the post-hoc gate; ensure they're spec-derived, never 30B-authored).
3. **Right-size the task envelope**: smaller, checkpointed, test-gated steps; stop expecting unattended whole-app builds.
4. **Evaluate Devstral-Small-24B / Qwen3-Coder-30B-A3B at INT8** for the coder slot.
5. **Freeze the review side**: keep the critic + VLM loop as the cheap signals they are; do not add a fourth reviewer.
6. **Park fine-tuning** until there's executable-trajectory data; revisit on the 7-month horizon cadence.

## Honest caveats on the evidence
- Vendor SWE-bench numbers are *best-scaffold upper bounds*; independent runs are 5+ points lower.
- The quantization→agentic conclusion is *assembled* from long-context + flip-doubling + error-compounding evidence; no
  single study measures an INT4-vs-FP16 *agent-trajectory* delta.
- The specific ~30B end-to-end figure is *interpolated* from 7B/24B/70B points, not directly measured.
- Best-of-N's coverage curve assumes *diverse* samples (temperature/seed/prompt variation); correlated samples flatten it.
