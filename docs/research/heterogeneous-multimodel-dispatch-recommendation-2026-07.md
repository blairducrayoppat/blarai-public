# Heterogeneous multi-model dispatch pipeline — recommendation

**Date:** 2026-07-17 · **Status:** RESEARCH / RECOMMENDATION (read-only; for the LA's later decision — no build, no config change, no ticket) · **Author:** research session (dev-side)
**Question (LA sketch):** Should BlarAI move dispatch to a heterogeneous 4-model pipeline — Qwen3.6-35B-A3B drafting the front (plan/tests/oracles), Qwen3-Coder-30B-A3B as coder, a **dense** Qwen3.6-27B as post-coder judge, and an open coordinator (14B or 27B)?

---

## Recommendation (read this first)

**Do not adopt the heterogeneous 4-model sketch. The single measured fact that decides it: the dense Qwen3.6-27B judge runs at 3.59 tokens/second on this Arc 140V — roughly 10x slower than any Mixture-of-Experts (MoE) model of the same size class — so a judge "invoked every dispatch" would dominate end-to-end wall time, not sharpen it.** The sketch also multiplies the two costs BlarAI is trying to shrink: it adds a second and third model **swap** per dispatch (the box holds only ~one 18–19 GB model at a time against the 31.323 GB ceiling), and it multiplies exposure to the untagged-thinking blocker (genai #3937) across three separate Qwen3.6 roles instead of one. The stronger direction — **already LA-set and in flight as ticket #930** — is the *opposite*: **consolidate onto ONE resident Qwen3.6-35B-A3B MoE** serving chatbot + dispatch-front + coordinator + vision, keeping the 30B-A3B coder as the *single* swap partner. That path is swap-equal-or-better than today, uses only fast MoE models, retires the Qwen3-VL-8B vision swap, and carries exactly one #3937 gate instead of three. If a dedicated post-coder judge is ever wanted, it must be an MoE (a second pass by the resident 35B, or the existing 30B "review" agent) — **never the dense 27B**.

### Decision table

| Option | Front: plan / tests / oracle | Coder | Post-coder judge | Coordinator | Vision | OVMS model-loads / dispatch | Qwen3.6 #3937 gate surface | Verdict |
|---|---|---|---|---|---|---|---|---|
| **Today (baseline)** | Qwen3-14B **dense, in-proc** — 17 tok/s spec-on | 30B-A3B (OVMS) | 14B critic on OVMS (**DORMANT** today) + deterministic gates | 14B | VL-8B (load-on-demand swap) | **1** (the 30B) | none (14B has clean tagged thinking) | reference |
| **Heterogeneous 4-model (the sketch)** | 35B-A3B | 30B-A3B | **27B DENSE — 3.59 tok/s** | 14B or 27B | (implicit, via 35B?) | **≥2–3** | **high** — draft + judge (+ coord) all Qwen3.6 | **NOT RECOMMENDED** |
| **Consolidation onto 35B (#930, in flight)** | 35B-A3B **MoE, in-proc** — 35 tok/s | 30B-A3B (OVMS) | resident-35B second pass, or the existing 30B review agent + gates | 35B (shared resident) | **35B absorbs VL-8B** | **1** (the 30B) | **one** gate (#4139), at the chatbot boundary | **RECOMMENDED** |

Bottom line: the sketch spends more RAM, more swaps, and more #3937 risk to add a judge that is physically too slow to sit hot. The consolidation gets a faster, multimodal, higher-quality front for the same swap budget and retires a whole model. Both are the *same* model-upgrade-watch revisit event and both are gated on the same fix (#4139) plus a quality-parity eval — but only the consolidation is worth the escalation.

---

## The current dispatch pipeline, stage by stage (what it ACTUALLY does today)

Mapped from `C:/Users/mrbla/agentic-setup/configs/model-profiles.json` (`call_sites`, lines 129–191 — today's real per-role policy), `C:/Users/mrbla/BlarAI/shared/fleet/swap_driver.py`, `swap_ops.py`, and the fleet PowerShell (`new-agent-task.ps1`, `start-llm.ps1`, `fleet-lib.ps1`). The dispatch runs in **three residency windows** because the box holds ~one big model at a time.

**Window A — Qwen3-14B resident IN-PROC (before step-aside), OpenVINO GenAI, greedy:**
1. **plan** (build the plan-graph / JobPlan) — 14B in-proc
2. **decompose** (idea → ordered fleet tasks) — 14B in-proc, `/no_think`
3. **oracle-author** (#748: write the spec-blind pytest acceptance oracle) — 14B in-proc, grammar off

The Assistant Orchestrator (AO) does 1–3 while the 14B is resident in-process, then **releases the in-proc 14B and spawns a detached `SwapDriver`** (`swap_driver.py`). This release/restore is an in-process GenAI dispose + later re-instantiation at launcher restart — **not** an OVMS `start-llm` load.

**Window B — Qwen3-Coder-30B-A3B resident on OVMS (the swap window):**
- ▶ **LOAD #1**: `start-llm.ps1 -Model coder-30b -Force` (`swap_ops.real_load_30b`) → 30B on OVMS.
4. **seed-oracle** (#690/#748: write + commit the oracle into the worktree) — deterministic, no model
5. **code** (best-of-N candidates; #689/#695) — **30B**, OVMS via the `:8099` proxy, temp 0.7 / top-p 0.8. Best-of-N width is complexity-driven (`Resolve-PassBudget`: simple 2 / moderate 3 / complex 8), *not* arch-driven.
6–10. **static-pregate** (#831 ruff E9/F821/F823 + `node --check`), **import-probe** (#822), **exec-smoke** (#830 boot floor), **wave-gate** (#740 W4 integration suite), **job-oracle** (#740 run the acceptance oracle) — **all deterministic subprocesses, no model call**, run while the 30B stays resident. These are DORMANT-by-default seams that activate under plan-graph mode.
11a. **review** (per-task in-fleet reviewer, advisory) — whatever coder model is loaded (30B), `opencode --agent review`.

**Window C — reload windows inside B (only when enabled):**
11b. **cross-model critic** (#687: post-merge critique→fix→re-critique) — **14B on OVMS**, its own load via `start-llm -Force` (▶ **LOAD #2**, swaps 30B→14B). **DORMANT today** (`BLARAI_ENABLE_CRITIC` unset). Each critic fix-lap adds 2 more loads (reload 30B to apply, reload 14B to re-judge).
12. **design-critique** (#688 Phase 3, visual surfaces only) — **VL-8B in-proc**, after `stop_ovms` unloads the 30B so the GPU is free. A design fix-lap reloads the 30B.
13. **report** (scorecard / verdict / JOB_SUMMARY / Vikunja post) — deterministic, after the 14B is restored in-proc.

**Loads per dispatch, today:** with the critic DORMANT (the default), **exactly ONE OVMS load** — the 30B. The 14B front and 14B restore are in-proc (no OVMS load). With the critic enabled: **two** OVMS loads, +2 per critic lap, +1 per design lap.

So the sketch's "14B plan → load 30B → reload for critic → restore 14B" is right in shape, but the live default is leaner than it sounds: **one** paid OVMS load per dispatch, and the front/restore model never touches OVMS.

---

## Evidence per criterion

### 1. Dense-27B serving speed — disqualifying for a hot judge; the MoE alternative is ~10x faster

**Measured, community-grade** (`docs/performance/benchmark_vlm_text_qwen3.6-27b-int4-ov_2026-07-08_16-21-18.json`; PERFORMANCE_LOG.md 2026-07-08):

| Qwen3.6-27B **dense** INT4, Arc 140V, OV GenAI 2026.2.1 | value |
|---|---|
| decode (median sustained) | **3.59 tok/s** (short answers 5–6; 256-tok runs 3.2–3.7) |
| prefill | **219 pp tok/s** (vs the 14B dense's ~1960 on the same silicon) |
| load | 33.1 s · GPU-committed 15.9 GB |

The cause is named in the eval doc (`docs/MODEL_EVALUATION_QWEN36_27B.md`): the 27B is **dense** (27B active params/token, ~2x the 14B's per-token compute) **and** its Gated-DeltaNet hybrid runs on **unoptimized GPU-plugin kernels** — the 219 pp prefill (9x below the 14B's) shows it is currently *compute-bound*, not bandwidth-bound. Physics ceiling for a dense 27B INT4 here is ~9.7 tok/s even at impossible 100% bandwidth efficiency; 11 tok/s is above the ceiling.

Contrast the **MoE** models of the same size class (only ~3.3B params active per token):

| model (INT4, Arc 140V) | decode | prefill | source |
|---|---|---|---|
| Qwen3.6-**35B**-A3B (official IR) | **34.97 tok/s** | 525 pp | `benchmark_vlm_text_qwen36-35b-a3b-int4-ov-OFFICIAL_2026-07-16_18-22-59.json` |
| Qwen3-Coder-**30B**-A3B | **38.6 tok/s** (flag off) / 31.3 (on) | 480 pp | PERFORMANCE_LOG 2026-06-29; `benchmark_ovms_coder-30b_*` |
| Qwen3-14B **dense** | 11.1 spec-off / **17.1 spec-on** | 1960 pp | PERFORMANCE_LOG 2026-06-28 |

**A dense-27B judge is ~10x slower than a 30B/35B-A3B judge and ~5x slower than the 14B spec-on.** A judge pass over a code diff is hundreds of tokens; at 3.59 tok/s that is minutes of hot-path latency per dispatch. **If a judge is wanted at all, it must be MoE.** (One honest nuance: a *dense* model can reason better than a same-size sparse MoE per token — the only real argument for the 27B. But 3.59 tok/s makes it unusable as a hot judge, and the pragmatic "dense judge" already exists: the 14B critic at 17 tok/s. The 27B's dense-quality edge does not survive its speed.)

Caveat named in the data: the 27B number is a **software** number (kernel immaturity), expected to move on OpenVINO version bumps — it is a standing re-measure, not a permanent physics wall. But it is today's number, and nothing has shipped to move it.

### 2. Swap cost — the sketch adds swaps; consolidation does not

The box holds ~one 18–19 GB model at a time: **35B-A3B resident ≈ 18.4 GB** (measured In-Use = 24.3 − 5.91 available, official-IR run) and **30B-A3B ≈ 18 GB** (manifest `resident_gb`). **18.4 + 18 = 36.4 GB > 31.323 GB ceiling** — front and coder **cannot** co-reside. Every front↔coder↔judge transition is therefore a real OVMS model-load.

Measured load costs:
- 30B OVMS load: **cold ~289 s, warm ~12 s** (compiled-model cache, #747 — payoff ~18–78 s saved/swap once warm; `docs/performance/ovms_compile_cache_coder30b_2026-07-06.json`).
- 14B load (spec-decode, warm cache): **~10.8 s** (PERFORMANCE_LOG).
- 35B official IR load: **44.2 s** (measured; cold-compile amortized after first).

Loads per dispatch:
- **Today:** 1 (the 30B). Front + restore in-proc.
- **Heterogeneous 4-model:** if front (35B) and coordinator share one resident model, you *still* swap out to the 30B coder and then to a judge. Judge = dense-27B → a 2nd OVMS load (33 s) **plus generation at 3.59 tok/s** (the dominant cost). Judge = 35B → swap 30B→35B (~44 s) then generate at 35 tok/s. **Either way ≥2 OVMS loads/dispatch, plus the judge generation**, before any fix-laps.
- **Consolidation onto 35B:** **still 1** OVMS load/dispatch (the 30B coder); front = resident 35B in-proc; **and the VL-8B vision load-on-demand is retired entirely.**

So on swap cost the ranking is unambiguous: **consolidation ≤ today < heterogeneous.**

### 3. Reconcile against the model-upgrade-watch record and its two named signals

SSOT: `docs/MODEL_EVALUATION_QWEN36_27B.md:97–123` (+ `docs/DECISION_REGISTER.md`, ADR-011/ADR-012). Standing doctrine: **Qwen3-14B stays; a swap is blocked on the OpenVINO substrate and revisited only on two named signals:**
1. **An OV-runnable Qwen3.6 spec-decode path lands** — native Multi-Token Prediction (MTP: genai PR #4065 + optimum-intel PR #1814, whose example exports the 35B-A3B) **or** DFlash (genai #3938). Today none has shipped; the 0.6B INT4 draft won't pair with any Qwen3.6 (vocab 248,320 ≠ Qwen3's ~152K), and a llama.cpp trial of the 0.6B draft on the 35B gave **0.0 acceptance / −37% throughput** (#769 c.2141). So any Qwen3.6 front runs **draftless** — but at 35 tok/s (MoE) that still beats the 14B's 17 tok/s spec-on.
2. **GPU-plugin kernel maturity** for the Gated-DeltaNet hybrid / unfused MoE-MLP kernels (mechanism: genai #3773 SDPA-fallback, openvino #36270). Re-measured at each version bump.

**Where the two proposals sit:** Adopting a Qwen3.6 model as the resident brain **is** the revisit event both signals gate — it is simultaneously a capability change (retire/absorb vision), a quality change (MoE ~3B-active replacing a dense 14B), a spec-decode re-establishment, and an ADR-012 amendment + full GPU re-validation. The **consolidation** has already been escalated and the LA set direction on it (#930, 2026-07-17). The **heterogeneous 4-model sketch sits OUTSIDE both named signals**: it is not the watched *swap* of the resident brain — it is a net-new *multi-model architecture* layered on top, and it re-introduces the dense-27B the eval doc already evaluated and rejected (throughput FAIL, 2026-07-08). It should not be treated as the revisit trigger; the consolidation is.

### 4. The thinking-tag issue (#3937 / #4139 / #923) — one gate for consolidation, three for the sketch

genai **#3937**: OpenVINO GenAI accepts `enable_thinking=False` but the Qwen3.6 model **ignores it**, and the `/no_think` soft-switch is ignored too — the model emits chain-of-thought **untagged** (no `<think>` wrapper), so the Policy-Agent `/no_think` mechanism (ADR-012 §2.4) breaks **and** the AO's tag-based strip cannot even hide it (`docs/performance/qwen36_27b_thinking_toggle_probe_2026-07-08.json`; reproduced on the 27B and reported on the 35B). This is the **hardest active blocker** for any Qwen3.6 model in an interactive/judge/draft role.

Fix in-flight: genai **PR #4139** ("Add enable_thinking / reasoning_budget_tokens to GenerationConfig") — **OPEN, not merged, last updated 2026-07-17** (GitHub API). BlarAI has an on-hardware verification build at `C:/Users/mrbla/builds/genai-pr4139` and a check-back on **2026-07-30** (#923); all upstream posts are LA-held.

How it constrains each role:
- **35B as chatbot/interactive** — gated hard (untagged CoT reaches the user). This is exactly the gate on #930.
- **35B/27B as dispatch-draft (plan/decompose/oracle-author)** — planner/oracle output is parsed as structured JSON; untagged CoT bleeding into that stream is a correctness hazard, so also gated.
- **27B/35B as judge** — a judge's verdict must be machine-parseable; untagged reasoning corrupts it → gated.
- **coordinator** — same parsing hazard → gated.

**The consolidation crosses this gate once (the chatbot boundary). The heterogeneous sketch crosses it three times (draft + judge + coordinator), each an independent Qwen3.6 surface** — strictly more exposure for no compensating benefit.

### 5. The opposite thesis — ONE fast multimodal model that REDUCES swaps (the recommended direction)

This is not hypothetical; it is **LA-directed and ticketed (#930, 2026-07-17)**, built on measured evidence:
- **Serving viability (gate A): GREEN on throughput.** 35B-A3B official IR = **35 tok/s draftless**, vs the 14B's 17 tok/s spec-on. The earlier 1.59 tok/s "inversion" was a **conversion artifact of an unofficial IR** — dead headline; the official Intel IR is 22x faster on decode (#769 c.2137).
- **Multimodal (gate B): YES.** The official `OpenVINO/Qwen3.6-35B-A3B-int4-ov` is `image-text-to-text` (VLMPipeline) — it **absorbs Qwen3-VL-8B** and its load-on-demand vision swap (#769 c.2132).
- **Quality + speed vs the incumbent vision model:** in the LA-reviewed head-to-head (#769 c.2153/c.2159), the 35B-A3B was the **better-quality** multimodal responder **and faster per turn** than the dense VL-8B (35B 20.1/14.3/15.4 s vs VL-8B 27.8/21.3/23.0 s). VL-8B (#550) retires in favor of the unified 35B.
- **RAM:** the consolidation trades *higher single-model RAM* (18.4 GB vs the 14B's ~10 GB) for *fewer models + no vision swap*. It still cannot co-reside with the 30B coder (36 GB > ceiling), so the coder swap is unchanged from today — the net swap topology is **≤ today**.

**Head-to-head verdict:** consolidation wins on every axis in the sketch's own criteria — swaps (1 vs ≥2–3), RAM (one 18 GB resident vs trying to juggle two/three 18 GB models), quality (a fast MoE front + multimodal vs a disqualified dense judge), and #3937 exposure (one gate vs three). The only thing the sketch offers that consolidation doesn't is *judge specialization* — and the specialization it picks (dense-27B) is the one option the hardware measurably cannot serve hot. If judge specialization is genuinely wanted later, do it with an MoE: a second pass by the resident 35B, or promote the existing DORMANT 30B "review" agent (stage 11a) — no new resident model, no new swap.

---

## Residual unknowns — what must be MEASURED before any front-model decision (either path)

1. **Answer-quality parity of the 35B as PLANNER / DECOMPOSE / ORACLE-AUTHOR — NOT YET MEASURED.** Every quality datapoint we hold for the 35B is *multimodal chat* (the vision head-to-head). The front-of-dispatch roles the sketch and the consolidation both target need reliable structured-JSON planning and spec-blind oracle authoring. **Instrument:** the eval suite with a model-dir override (`python -m evals.run --suite all`, blocked today on the hardcoded 14B path — the override is #931, building) **plus** a dispatch-battery A/B (35B-front vs 14B-front over the golden fixture boards). This is the consolidation's stated hard gate and it is the single biggest open question for *any* front swap. **Until it passes, neither the consolidation-front nor a heterogeneous-front is decidable.**
2. **35B In-Use RAM on a LIVE box.** The 18.4 GB residency was measured leaned (app closed, AO down, VM off). The consolidation needs the 35B resident *alongside* the live WinUI app, launcher, and NPU embeddings. **Instrument:** In-Use = Total − Available with the full stack up. If In-Use is tight, the 30B coder swap headroom must be re-verified.
3. **#4139 on-hardware behavior on the official 35B.** The fix is unmerged and the PR author never tested Qwen3.6; BlarAI's build at `builds/genai-pr4139` is the instrument. Until a build demonstrably suppresses/tags the 35B's thinking on *this* stack, the whole family stays interactive-gated. **Instrument:** the `probe_qwen36_thinking_toggle` shape against the from-source build; check-back #923 (2026-07-30).
4. **35B long-context decode curve.** No protocol-clean long-context instrument exists for the VLMPipeline class (the bench harness uses a fixed 256-tok prompt set; `kv_cache_sweep.py` is LLMPipeline). Dispatch plans and oracle context can be long; the 35 tok/s figure is short-generation. **Instrument:** a new VLMPipeline long-context methodology (must clear the protocol bar — do not mint it unreviewed).
5. **Kernel-maturity re-measure of the dense 27B** at each OpenVINO bump — only relevant if the dense-judge idea is ever revived; today it stays FAIL.

**Named as NOT measured in this writeup:** any 35B quality-on-dispatch-tasks number; 35B co-resident cost with the live app; a judge-pass latency for a 27B/35B judge over a real diff; long-context decode for any Qwen3.6 model.

---

## Sources (on disk unless noted)

- Pipeline/roles: `agentic-setup/configs/model-profiles.json` (call_sites L129–191); `shared/fleet/swap_driver.py`, `swap_ops.py`; `agentic-setup/scripts/{new-agent-task,start-llm,fleet-lib}.ps1`.
- 27B dense: `docs/performance/benchmark_vlm_text_qwen3.6-27b-int4-ov_2026-07-08_16-21-18.json`; `docs/MODEL_EVALUATION_QWEN36_27B.md`.
- 35B-A3B official: `docs/performance/benchmark_vlm_text_qwen36-35b-a3b-int4-ov-OFFICIAL_2026-07-16_18-22-59.json`.
- 30B / 14B / spec-decode / swap-cache: `PERFORMANCE_LOG.md` (2026-06-28, 2026-06-29, 2026-07-06 #747); `docs/performance/ovms_compile_cache_coder30b_2026-07-06.json`.
- Decisions/watch: Vikunja #769 (c.2137 official-IR de-caveat, c.2153/c.2159 head-to-head + LA verdict), #930 (consolidation direction), #923 (#4139 check-back), #931 (eval override), #550 (VL-8B retire); ADR-011/012; model-upgrade-watch `docs/MODEL_EVALUATION_QWEN36_27B.md:97–123`.
- genai PR #4139 state: GitHub API, OPEN/unmerged as of 2026-07-17.
